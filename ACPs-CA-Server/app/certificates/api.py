"""
证书管理 API 路由
"""

from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, HTTPException, status, Depends, Query, Path
from fastapi.responses import PlainTextResponse
from sqlmodel import Session

from app.core.db_session import engine
from app.common import (
    CertificateResponse,
    CertificateListResponse,
    PagedResponse,
    CertificateType,
    CertificateStatus,
    CreateRootCertificateRequest,
    CreateIntermediateCertificateRequest,
)
from .services import CertificateManagementService


router = APIRouter()


def get_certificate_service() -> CertificateManagementService:
    """依赖注入：获取证书管理服务"""
    return CertificateManagementService(Session(engine))


# 根证书管理
@router.get("/root", response_model=List[CertificateResponse], summary="获取根证书列表")
async def get_root_certificates(
    service: CertificateManagementService = Depends(get_certificate_service),
):
    """获取所有根证书"""
    certificates = service.get_root_certificates()
    return certificates


@router.post("/root", response_model=CertificateResponse, summary="创建根证书")
async def create_root_certificate(
    request: CreateRootCertificateRequest,
    service: CertificateManagementService = Depends(get_certificate_service),
):
    """
    创建根证书（系统级操作）
    """
    try:
        certificate = service.create_root_certificate(
            request.subject_name, request.validity_days
        )
        return certificate
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建根证书失败: {str(e)}",
        )


@router.post(
    "/root/{certificate_id}/renew",
    response_model=CertificateResponse,
    summary="续期根证书",
)
async def renew_root_certificate(
    certificate_id: UUID = Path(..., description="证书ID"),
    validity_days: Optional[int] = None,
    service: CertificateManagementService = Depends(get_certificate_service),
):
    """续期根证书（系统级操作）"""
    certificate = service.renew_certificate(certificate_id, validity_days)
    if not certificate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="证书不存在")
    return certificate


@router.post(
    "/root/{certificate_id}/revoke",
    response_model=CertificateResponse,
    summary="吊销根证书",
)
async def revoke_root_certificate(
    certificate_id: UUID = Path(..., description="证书ID"),
    reason: str = Query(..., description="吊销原因"),
    service: CertificateManagementService = Depends(get_certificate_service),
):
    """吊销根证书（系统级操作）"""
    certificate = service.revoke_certificate(certificate_id, reason)
    if not certificate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="证书不存在")
    return certificate


# 中间证书管理
@router.get(
    "/intermediate",
    response_model=List[CertificateResponse],
    summary="获取中间证书列表",
)
async def get_intermediate_certificates(
    parent_id: Optional[UUID] = Query(None, description="父证书ID"),
    service: CertificateManagementService = Depends(get_certificate_service),
):
    """获取中间证书列表"""
    certificates = service.get_intermediate_certificates(parent_id)
    return certificates


@router.get(
    "/intermediate/{certificate_id}",
    response_model=CertificateResponse,
    summary="获取特定中间证书",
)
async def get_intermediate_certificate(
    certificate_id: UUID = Path(..., description="证书ID"),
    service: CertificateManagementService = Depends(get_certificate_service),
):
    """获取特定中间证书详情"""
    certificate = service.get_certificate_by_id(certificate_id)
    if not certificate or certificate.certificate_type != CertificateType.INTERMEDIATE:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="中间证书不存在"
        )
    return certificate


@router.post(
    "/intermediate", response_model=CertificateResponse, summary="创建中间证书"
)
async def create_intermediate_certificate(
    request: CreateIntermediateCertificateRequest,
    service: CertificateManagementService = Depends(get_certificate_service),
):
    """
    创建中间证书（系统级操作）
    """
    certificate = service.create_intermediate_certificate(
        request.subject_name, request.parent_certificate_id, request.validity_days
    )
    if not certificate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="父证书不存在或无效"
        )
    return certificate


@router.post(
    "/intermediate/{certificate_id}/renew",
    response_model=CertificateResponse,
    summary="续期中间证书",
)
async def renew_intermediate_certificate(
    certificate_id: UUID = Path(..., description="证书ID"),
    validity_days: Optional[int] = None,
    service: CertificateManagementService = Depends(get_certificate_service),
):
    """续期中间证书（系统级操作）"""
    certificate = service.renew_certificate(certificate_id, validity_days)
    if not certificate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="证书不存在")
    return certificate


@router.post(
    "/intermediate/{certificate_id}/revoke",
    response_model=CertificateResponse,
    summary="吊销中间证书",
)
async def revoke_intermediate_certificate(
    certificate_id: UUID = Path(..., description="证书ID"),
    reason: str = Query(..., description="吊销原因"),
    service: CertificateManagementService = Depends(get_certificate_service),
):
    """吊销中间证书（系统级操作）"""
    certificate = service.revoke_certificate(certificate_id, reason)
    if not certificate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="证书不存在")
    return certificate


# 用户证书查询与管理
@router.get("", response_model=PagedResponse, summary="查询证书列表")
async def list_certificates(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    certificate_type: Optional[CertificateType] = Query(
        None, description="证书类型过滤"
    ),
    status: Optional[CertificateStatus] = Query(None, description="状态过滤"),
    aic: Optional[str] = Query(None, description="AIC过滤"),
    service: CertificateManagementService = Depends(get_certificate_service),
):
    """查询证书列表，支持分页和过滤"""
    certificates, total = service.list_certificates(
        page=page,
        page_size=page_size,
        certificate_type=certificate_type,
        status=status,
        aic=aic,
    )

    # 转换为列表响应格式
    items = [CertificateListResponse.model_validate(cert) for cert in certificates]

    return PagedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get(
    "/{certificate_id}", response_model=CertificateResponse, summary="获取特定证书详情"
)
async def get_certificate(
    certificate_id: UUID = Path(..., description="证书ID"),
    service: CertificateManagementService = Depends(get_certificate_service),
):
    """获取特定证书的详细信息"""
    certificate = service.get_certificate_by_id(certificate_id)
    if not certificate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="证书不存在")
    return certificate


@router.get(
    "/{certificate_id}/download", response_class=PlainTextResponse, summary="下载证书"
)
async def download_certificate(
    certificate_id: UUID = Path(..., description="证书ID"),
    service: CertificateManagementService = Depends(get_certificate_service),
):
    """下载证书PEM格式文件"""
    certificate = service.get_certificate_by_id(certificate_id)
    if not certificate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="证书不存在")

    return PlainTextResponse(
        content=certificate.certificate_pem,
        media_type="application/x-pem-file",
        headers={
            "Content-Disposition": f"attachment; filename=certificate-{certificate.serial_number}.pem"
        },
    )


@router.get(
    "/{certificate_id}/chain",
    response_model=List[CertificateResponse],
    summary="获取证书链",
)
async def get_certificate_chain(
    certificate_id: UUID = Path(..., description="证书ID"),
    service: CertificateManagementService = Depends(get_certificate_service),
):
    """获取完整的证书链"""
    chain = service.get_certificate_chain(certificate_id)
    if not chain:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="证书不存在")
    return chain


@router.post(
    "/{certificate_id}/revoke",
    response_model=CertificateResponse,
    summary="手动吊销证书",
)
async def revoke_certificate(
    certificate_id: UUID = Path(..., description="证书ID"),
    reason: str = Query(..., description="吊销原因"),
    service: CertificateManagementService = Depends(get_certificate_service),
):
    """手动吊销证书（管理员操作）"""
    certificate = service.revoke_certificate(certificate_id, reason)
    if not certificate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="证书不存在")
    return certificate


@router.get(
    "/expiring", response_model=List[CertificateResponse], summary="获取即将过期的证书"
)
async def get_expiring_certificates(
    days_ahead: int = Query(30, ge=1, le=365, description="提前天数"),
    service: CertificateManagementService = Depends(get_certificate_service),
):
    """获取即将过期的证书列表，用于续期提醒"""
    certificates = service.get_expiring_certificates(days_ahead)
    return certificates
