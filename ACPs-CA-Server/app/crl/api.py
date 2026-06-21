"""
CRL API路由

实现CRL (Certificate Revocation List) 相关的API端点。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status, Query
from sqlmodel import Session, select

from app.core.db_session import get_session
from app.common import (
    CRLService,
    CRLInfoResponse,
    CRLDistributionPointsResponse,
    CRLResponse,
    CRLListResponse,
    CRLStatus,
)

router = APIRouter()


def get_crl_service(db: Session = Depends(get_session)) -> CRLService:
    """获取CRL服务实例"""
    return CRLService(db)


@router.get(
    "",
    summary="下载CRL",
    description="下载证书吊销列表",
    response_class=Response,
)
async def download_crl(
    format: str = Query(
        "der", pattern="^(pem|der)$", description="CRL格式 (pem 或 der)"
    ),
    service: CRLService = Depends(get_crl_service),
):
    """
    下载证书吊销列表

    权限级别: public
    """
    current_crl = service.get_current_crl()
    if not current_crl:
        # 如果没有当前CRL，尝试生成一个新的
        try:
            current_crl = service.generate_new_crl(issuer="Agent CA")
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate CRL: {str(e)}",
            )

    if format == "pem":
        return Response(
            content=current_crl.crl_pem,
            media_type="application/x-pem-file",
            headers={
                "Content-Disposition": 'attachment; filename="agent-ca.crl"',
                "Cache-Control": "max-age=3600",
                "Last-Modified": current_crl.this_update.strftime(
                    "%a, %d %b %Y %H:%M:%S GMT"
                ),
                "ETag": f'"{current_crl.version}"',
            },
        )
    else:
        return Response(
            content=current_crl.crl_der,
            media_type="application/pkix-crl",
            headers={
                "Content-Disposition": 'attachment; filename="agent-ca.crl"',
                "Cache-Control": "max-age=3600",
                "Last-Modified": current_crl.this_update.strftime(
                    "%a, %d %b %Y %H:%M:%S GMT"
                ),
                "ETag": f'"{current_crl.version}"',
            },
        )


@router.get(
    "/current",
    summary="获取当前CRL",
    description="获取最新的证书撤销列表",
    response_class=Response,
)
async def get_current_crl(service: CRLService = Depends(get_crl_service)):
    """
    获取当前有效的CRL

    权限级别: public - CRL是公开信息，任何客户端都可以下载来验证证书状态
    """
    current_crl = service.get_current_crl()
    if not current_crl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No current CRL available"
        )

    # 返回CRL的DER格式内容
    return Response(
        content=current_crl.crl_der,
        media_type="application/pkix-crl",
        headers={
            "Content-Disposition": 'attachment; filename="agent-ca.crl"',
            "Cache-Control": "max-age=3600",
            "Last-Modified": current_crl.this_update.strftime(
                "%a, %d %b %Y %H:%M:%S GMT"
            ),
            "ETag": f'"{current_crl.version}"',
        },
    )


@router.get(
    "/current/pem",
    summary="获取当前CRL (PEM格式)",
    description="获取最新的证书撤销列表 (PEM格式)",
    response_class=Response,
)
async def get_current_crl_pem(service: CRLService = Depends(get_crl_service)):
    """
    获取当前有效的CRL (PEM格式)

    权限级别: public - CRL是公开信息，任何客户端都可以下载来验证证书状态
    """
    current_crl = service.get_current_crl()
    if not current_crl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No current CRL available"
        )

    # 返回CRL的PEM格式内容
    return Response(
        content=current_crl.crl_pem,
        media_type="application/x-pem-file",
        headers={
            "Content-Disposition": 'attachment; filename="agent-ca.crl"',
            "Cache-Control": "max-age=3600",
            "Last-Modified": current_crl.this_update.strftime(
                "%a, %d %b %Y %H:%M:%S GMT"
            ),
            "ETag": f'"{current_crl.version}"',
        },
    )


@router.get(
    "/info",
    response_model=CRLInfoResponse,
    summary="获取CRL信息",
    description="获取CRL的元数据信息",
)
async def get_crl_info(service: CRLService = Depends(get_crl_service)):
    """
    获取CRL元数据信息

    权限级别: public - CRL元数据信息公开可访问
    """
    current_crl = service.get_current_crl()
    if not current_crl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No current CRL available"
        )

    distribution_point = (
        current_crl.distribution_points[0]
        if current_crl.distribution_points
        else "https://ca.example.com/api/v1/crl/current"
    )

    return CRLInfoResponse(
        version=current_crl.version,
        issuer=current_crl.issuer,
        this_update=current_crl.this_update,
        next_update=current_crl.next_update,
        revoked_certificates_count=current_crl.revoked_certificates_count,
        crl_size=current_crl.crl_size,
        distribution_point=distribution_point,
        signature={
            "algorithm": current_crl.signature_algorithm,
            "key_id": current_crl.signature_key_id,
        },
    )


@router.get(
    "/version/{version}",
    summary="获取历史CRL",
    description="获取指定版本的历史CRL",
    response_class=Response,
)
async def get_crl_by_version(
    version: str, service: CRLService = Depends(get_crl_service)
):
    """
    获取指定版本的历史CRL

    权限级别: public - 历史CRL信息公开可访问

    Args:
        version: CRL版本号，格式为YYYYMMDDHH
    """
    crl = service.get_crl_by_version(version)
    if not crl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CRL version {version} not found",
        )

    # 返回CRL的DER格式内容
    return Response(
        content=crl.crl_der,
        media_type="application/pkcs7-crl",
        headers={
            "Content-Disposition": f'attachment; filename="agent-ca-{version}.crl"',
            "Cache-Control": "max-age=86400",
            "Last-Modified": crl.this_update.strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "ETag": f'"{crl.version}"',
        },
    )


@router.get(
    "/distribution-points",
    response_model=CRLDistributionPointsResponse,
    summary="获取CRL分发点配置",
    description="获取CRL分发点的配置信息",
)
async def get_crl_distribution_points(service: CRLService = Depends(get_crl_service)):
    """
    获取CRL分发点配置

    权限级别: public - 分发点配置信息公开可访问
    """
    distribution_points = service.get_crl_distribution_points()
    return CRLDistributionPointsResponse(**distribution_points)


@router.get(
    "/list",
    response_model=CRLListResponse,
    summary="获取CRL列表",
    description="获取CRL的历史列表（需要管理员权限）",
)
async def get_crl_list(
    status: Optional[CRLStatus] = Query(None, description="CRL状态过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    service: CRLService = Depends(get_crl_service),
):
    """
    获取CRL列表

    权限级别: admin - CRL管理信息需要管理员权限

    Note: 这里暂时开放为public，实际部署时应该加上认证
    """
    crls, total = service.get_crl_list(status=status, page=page, page_size=page_size)

    total_pages = (total + page_size - 1) // page_size

    return CRLListResponse(
        items=[CRLResponse.from_orm(crl) for crl in crls],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post(
    "/refresh",
    response_model=CRLInfoResponse,
    summary="刷新CRL",
    description="重新生成当前CRL以包含最新的吊销信息",
)
async def refresh_crl(service: CRLService = Depends(get_crl_service)):
    """
    刷新CRL

    权限级别: admin - CRL重新生成是管理操作
    """
    try:
        # 重新生成CRL（这个方法内部会处理旧CRL的状态）
        new_crl = service.generate_new_crl(
            issuer="CN=CA,O=Example,C=CN", next_update_hours=24
        )

        # 返回新CRL信息
        distribution_point = (
            new_crl.distribution_points[0]
            if new_crl.distribution_points
            else "https://ca.example.com/api/v1/crl/current"
        )

        return CRLInfoResponse(
            version=new_crl.version,
            issuer=new_crl.issuer,
            this_update=new_crl.this_update,
            next_update=new_crl.next_update,
            revoked_certificates_count=new_crl.revoked_certificates_count,
            crl_size=new_crl.crl_size,
            distribution_point=distribution_point,
            signature={
                "algorithm": new_crl.signature_algorithm,
                "key_id": new_crl.signature_key_id,
            },
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refresh CRL: {str(e)}",
        )


@router.get(
    "/detail",
    summary="获取CRL详细信息",
    description="获取当前CRL的详细信息，包括所有吊销证书",
)
async def get_crl_detail(service: CRLService = Depends(get_crl_service)):
    """
    获取CRL详细信息

    权限级别: public - CRL详细信息公开可访问
    """
    current_crl = service.get_current_crl()
    if not current_crl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No current CRL available"
        )

    # 获取吊销证书条目（从数据库，保持原始序列号）
    try:
        from app.common.crl_model import RevokedCertificateEntry

        # 获取当前CRL的吊销证书条目
        statement = (
            select(RevokedCertificateEntry)
            .where(RevokedCertificateEntry.crl_id == current_crl.id)
            .order_by(RevokedCertificateEntry.revocation_date)
        )
        revoked_entries = service.db.exec(statement).all()

        revoked_certificates = []
        for entry in revoked_entries:
            # 获取吊销原因字符串 - 注意：RevocationReason.value 直接就是正确的值
            reason = (
                entry.revocation_reason.value
                if entry.revocation_reason
                else "unspecified"
            )

            revoked_certificates.append(
                {
                    "serialNumber": entry.serial_number,  # 使用原始序列号
                    "revocationDate": entry.revocation_date.isoformat(),
                    "reason": reason,
                }
            )

        return {
            "version": current_crl.version,
            "issuer": current_crl.issuer,
            "thisUpdate": current_crl.this_update.isoformat(),
            "nextUpdate": current_crl.next_update.isoformat(),
            "revokedCertificates": revoked_certificates,
            "revokedCertificatesCount": len(revoked_certificates),
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse CRL: {str(e)}",
        )
