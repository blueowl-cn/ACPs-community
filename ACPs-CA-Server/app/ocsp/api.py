"""
OCSP API路由

实现OCSP (Online Certificate Status Protocol) 相关的API端点。
"""

import base64

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlmodel import Session

from app.core.db_session import get_session
from app.common import (
    OCSPService,
    OCSPBatchRequest,
    OCSPBatchResponse,
    OCSPResponderInfo,
    OCSPStatsResponse,
)

router = APIRouter()


def get_ocsp_service(db: Session = Depends(get_session)) -> OCSPService:
    """获取OCSP服务实例"""
    return OCSPService(db)


@router.post(
    "/batch",
    response_model=OCSPBatchResponse,
    summary="批量OCSP查询",
    description="查询多个证书的状态",
)
async def ocsp_batch_request(
    batch_request: OCSPBatchRequest,
    service: OCSPService = Depends(get_ocsp_service),
):
    """
    批量OCSP查询

    权限级别: public - 批量OCSP查询同样是公开服务
    """
    try:
        # 转换请求格式
        certificates = []
        for cert_req in batch_request.certificates:
            certificates.append(
                {
                    "serial_number": cert_req.serial_number,
                    "issuer_key_hash": cert_req.issuer_key_hash,
                }
            )

        # 批量检查证书状态
        responses = service.batch_check_certificates(certificates)

        # 转换响应格式
        from app.common import OCSPSingleResponse
        from app.common.time_utils import beijing_now

        ocsp_responses = []
        for resp in responses:
            ocsp_responses.append(
                OCSPSingleResponse(
                    serial_number=resp["serial_number"],
                    status=resp["status"],
                    this_update=resp["this_update"],
                    next_update=resp["next_update"],
                    revocation_time=resp.get("revocation_time"),
                    revocation_reason=resp.get("revocation_reason"),
                )
            )

        responder = service.get_active_responder()
        responder_name = responder.name if responder else "Agent CA OCSP Responder"

        return OCSPBatchResponse(
            responses=ocsp_responses,
            responder_id=responder_name,
            produced_at=beijing_now(),
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch OCSP processing failed: {str(e)}",
        )


@router.get(
    "/responder/info",
    response_model=OCSPResponderInfo,
    summary="获取OCSP响应器信息",
    description="获取OCSP响应器的配置信息",
)
async def get_ocsp_responder_info(service: OCSPService = Depends(get_ocsp_service)):
    """
    获取OCSP响应器信息

    权限级别: public - OCSP响应器信息公开可访问
    """
    try:
        responder_info = service.get_responder_info()
        return OCSPResponderInfo(**responder_info)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OCSP responder not found: {str(e)}",
        )


@router.get(
    "/stats",
    response_model=OCSPStatsResponse,
    summary="获取OCSP统计信息",
    description="获取OCSP服务的统计数据",
)
async def get_ocsp_statistics(service: OCSPService = Depends(get_ocsp_service)):
    """
    获取OCSP统计信息

    权限级别: public - 基本统计信息公开可访问

    Note: 实际部署时可能需要管理员权限
    """
    try:
        stats = service.get_ocsp_statistics()
        return OCSPStatsResponse(**stats)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get OCSP statistics: {str(e)}",
        )


@router.post(
    "",
    summary="OCSP状态查询 (POST方法)",
    description="使用POST方法查询证书状态",
    response_class=Response,
)
async def ocsp_request_post(
    request: Request,
    service: OCSPService = Depends(get_ocsp_service),
):
    """
    OCSP状态查询 (POST方法)

    权限级别: public - OCSP查询是公开服务，任何客户端都可以验证证书状态
    """
    try:
        # 读取请求体
        request_der = await request.body()

        if not request_der:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Empty OCSP request"
            )

        # 获取客户端IP
        client_ip = request.client.host if request.client else None

        # 处理OCSP请求
        response_der, processing_time = service.process_ocsp_request(
            request_der, client_ip
        )

        return Response(
            content=response_der,
            media_type="application/ocsp-response",
            headers={
                "Cache-Control": "max-age=3600",
                "X-Processing-Time-MS": str(processing_time),
            },
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid OCSP request: {str(e)}",
        )


@router.get(
    "/{base64_request}",
    summary="OCSP状态查询 (GET方法)",
    description="使用GET方法查询证书状态",
    response_class=Response,
)
async def ocsp_request_get(
    base64_request: str,
    request: Request,
    service: OCSPService = Depends(get_ocsp_service),
):
    """
    OCSP状态查询 (GET方法)

    权限级别: public - OCSP查询是公开服务，任何客户端都可以验证证书状态

    Args:
        base64_request: Base64URL编码的OCSP请求
    """
    try:
        # 解码Base64URL请求
        # 注意：URL中的Base64编码可能会有填充问题
        request_der = base64.urlsafe_b64decode(base64_request + "==")

        # 获取客户端IP
        client_ip = request.client.host if request.client else None

        # 处理OCSP请求
        response_der, processing_time = service.process_ocsp_request(
            request_der, client_ip
        )

        return Response(
            content=response_der,
            media_type="application/ocsp-response",
            headers={
                "Cache-Control": "max-age=3600",
                "X-Processing-Time-MS": str(processing_time),
            },
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid OCSP request: {str(e)}",
        )


@router.get(
    "/certificate/{serial_number}",
    summary="简单OCSP状态查询",
    description="通过证书序列号查询证书状态（简化接口）",
)
async def get_certificate_status(
    serial_number: str,
    service: OCSPService = Depends(get_ocsp_service),
):
    """
    简单OCSP状态查询

    权限级别: public - 简化的证书状态查询接口

    Args:
        serial_number: 证书序列号
    """
    try:
        # 使用服务层查询证书状态
        certificate_status = service.get_certificate_status(serial_number)

        if not certificate_status:
            return {
                "serialNumber": serial_number,
                "certificateStatus": "unknown",
                "thisUpdate": None,
                "nextUpdate": None,
            }

        return certificate_status

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get certificate status: {str(e)}",
        )
