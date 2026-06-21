"""
扩展 API 路由

根据 ATR-DESIGN 第四章规范实现扩展功能，包括：
1. 获取信任包 (Trust Bundle)
2. 被动吊销通知 (Revoke Notify)
"""

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, ConfigDict
from sqlmodel import Session

from app.core.db_session import get_session
from app.core.ca_manager import get_ca_manager
from app.common import beijing_now, format_datetime
from .services import CertificateManagementService

class RetrieveResponse(BaseModel):
    """检索响应模型"""

    aic: str  # Agent Identity Code
    cert: str  # 证书内容（PEM 格式）
    version: Optional[int] = None  # 证书版本号
    retrieved_at: str = Field(..., serialization_alias="retrievedAt")  # 检索时间 (ISO8601)

    model_config = ConfigDict(populate_by_name=True)


class RetrieveByCertRequest(BaseModel):
    """按证书反查请求"""

    cert_pem: str = Field(..., serialization_alias="certPem", description="证书内容（PEM 格式）")

    model_config = ConfigDict(populate_by_name=True)


router = APIRouter()


def get_certificate_service(
    db: Session = Depends(get_session),
) -> CertificateManagementService:
    """依赖注入：获取证书管理服务"""
    return CertificateManagementService(db)


def get_revocation_reason_text(reason_code: int) -> str:
    """获取吊销原因文本描述"""
    reason_map = {
        0: "unspecified",  # 未指定
        1: "keyCompromise",  # 密钥泄露
        2: "cACompromise",  # CA 泄露
        3: "affiliationChanged",  # 隶属关系变更
        4: "superseded",  # 被替代
        5: "cessationOfOperation",  # 停止运营
    }
    return reason_map.get(reason_code, "unspecified")


# --- 数据模型 ---


class ManagementRevokeRequest(BaseModel):
    """管理端吊销请求"""

    aic: str = Field(..., description="Agent Identity Code")
    reason: int = Field(..., description="吊销原因代码 (0-5)")


class ManagementRevokeResponse(BaseModel):
    """管理端吊销响应"""

    aic: str
    revocation_reason: str = Field(..., serialization_alias="revocationReason")
    revoked_at: str = Field(..., serialization_alias="revokedAt")
    revoked_cert_count: int = Field(..., serialization_alias="revokedCertCount")

    model_config = ConfigDict(populate_by_name=True)


# --- API 端点 ---


@router.get(
    "/trust-bundle",
    summary="获取信任包 (Trust Bundle)",
    description="获取 CA 的信任包，包含本 CA 的根证书以及本 CA 所信任的其他 CA 的根证书。",
    response_class=Response,
)
async def get_trust_bundle():
    """
    获取信任包 (Trust Bundle)

    权限级别: public - 获取信任包是建立 mTLS 连接的前提
    """
    try:
        ca_manager = get_ca_manager()
        # 目前仅返回本 CA 的证书，未来可扩展为包含其他互信 CA 证书
        ca_cert_pem = ca_manager.get_ca_certificate_pem()

        return Response(
            content=ca_cert_pem,
            media_type="application/x-pem-file",
            headers={
                "Cache-Control": "public, max-age=3600",
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve trust bundle: {str(e)}",
        )


@router.post(
    "/revoke-notify",
    response_model=ManagementRevokeResponse,
    summary="被动吊销通知",
    description="当 Registry Server 中的 Agent 状态变更（如删除、禁用）时，通知 CA Server 吊销相关证书。",
)
async def revoke_notify(
    request: ManagementRevokeRequest,
    service: CertificateManagementService = Depends(get_certificate_service),
) -> ManagementRevokeResponse:
    """
    被动吊销通知

    权限级别: internal/mTLS - 仅限受信任的内部组件调用

    Args:
        request: 吊销请求，包含 AIC 和吊销原因
        service: 证书管理服务

    Returns:
        ManagementRevokeResponse: 吊销结果
    """
    # 验证 AIC 格式 TODO: 更严格的 AIC 格式验证
    if not request.aic or len(request.aic) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid AIC format"
        )

    # 验证吊销原因代码
    if request.reason < 0 or request.reason > 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid revocation reason code. Must be between 0-5",
        )

    try:
        # 获取吊销原因文本
        reason_text = get_revocation_reason_text(request.reason)

        # 批量吊销证书
        revoked_count = service.revoke_certificates_by_aic(request.aic, reason_text)

        # 构造响应
        return ManagementRevokeResponse(
            aic=request.aic,
            revocation_reason=reason_text,
            revoked_at=format_datetime(beijing_now()),
            revoked_cert_count=revoked_count,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process revocation notification: {str(e)}",
        )


@router.get(
    "/retrieve/aic/",
    response_model=RetrieveResponse,
    summary="检索 Agent 证书",
    description="根据 AIC 和版本号，检索相关证书",
)
async def retrieve_agent_certificate_by_aic(
    aic: str,
    version: Optional[int] = Query(None, description="版本号（可选）；不传则返回最新有效证书"),
    service: CertificateManagementService = Depends(get_certificate_service),
) -> RetrieveResponse:
    """
    检索 Agent 证书

    根据 ATR-DESIGN 规范，检索指定 AIC 和版本号的证书。
    如果未指定版本号，则检索最新版本的状态为"valid" 证书。

    Args:
        aic: Agent Identity Code
        version: 版本号（可选）
        service: 证书管理服务

    Returns:
        RetrieveResponse: 检索结果，包含证书内容等信息

    Raises:
        HTTPException: 当 AIC 格式无效或没有找到相关证书时
    """
    # 验证 AIC 格式
    if not aic or len(aic) != 32:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid AIC format"
        )

    try:
        certificate = service.retrieve_certificate_by_aic_and_version(
            aic=aic, version=version
        )
        if not certificate:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Certificate not found",
            )

        return RetrieveResponse(
            aic=certificate.aic,
            cert=certificate.certificate_pem,
            version=certificate.version,
            retrieved_at=format_datetime(beijing_now()),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve certificate: {str(e)}",
        )


@router.post(
    "/retrieve/cert",
    response_model=RetrieveResponse,
    summary="检索 Agent 证书 索引",
    description="根据证书，查询相关证书信息",
)
async def retrieve_agent_certificate_by_cert(
    request: RetrieveByCertRequest = Body(...),
    service: CertificateManagementService = Depends(get_certificate_service),
) -> RetrieveResponse:
    """
    检索 Agent 证书

    根据 ATR-DESIGN 规范，检索指定证书的相关信息。

    Args:
        cert_pem: 证书内容（PEM 格式）
        service: 证书管理服务
    Returns:
        RetrieveResponse: 检索结果，包含证书内容等信息
    Raises:
        HTTPException: 当证书格式无效或没有找到相关证书时
    """
    try:
        cert_pem = request.cert_pem
        if not cert_pem or "BEGIN CERTIFICATE" not in cert_pem:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid certificate PEM format",
            )

        certificate = service.retrieve_certificate_by_cert(cert_pem)
        if not certificate:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Certificate not found",
            )

        return RetrieveResponse(
            aic=certificate.aic,
            cert=certificate.certificate_pem,
            version=certificate.version,
            retrieved_at=format_datetime(beijing_now()),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve certificate: {str(e)}",
        )

