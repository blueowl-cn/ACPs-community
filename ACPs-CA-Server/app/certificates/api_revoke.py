"""
证书吊销 API 路由

根据 ATR-DESIGN 第五章规范实现证书吊销功能。
当 Registry Server 中的 Agent 被删除或禁用时，通知 CA Server 吊销相关证书。
"""

from typing import Dict, Any

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.core.db_session import get_session
from app.common import beijing_now, format_datetime
from .services import CertificateManagementService


class RevokeRequest(BaseModel):
    """吊销请求模型"""

    aic: str  # Agent Identity Code
    reason: int  # 吊销原因代码 (0-5)


class RevokeResponse(BaseModel):
    """吊销响应模型"""

    aic: str  # Agent Identity Code
    revocation_reason: str  # 吊销原因
    revoked_at: str  # 吊销时间 (ISO8601)
    revoked_cert_count: int  # 吊销的证书数量


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


@router.post(
    "/revoke",
    response_model=RevokeResponse,
    summary="吊销 Agent 证书",
    description="当 Registry Server 中的 Agent 被删除或禁用时，批量吊销该 AIC 的所有有效证书",
)
async def revoke_agent_certificates(
    request: RevokeRequest,
    service: CertificateManagementService = Depends(get_certificate_service),
) -> RevokeResponse:
    """
    批量吊销 Agent 证书

    根据 ATR-DESIGN 规范，当收到 Registry Server 的吊销通知时：
    1. 检查 AIC 对应的所有状态为 "pending" 或 "valid" 的证书
    2. 将这些证书全部吊销
    3. 返回吊销结果

    Args:
        request: 吊销请求，包含 AIC 和吊销原因
        service: 证书管理服务

    Returns:
        RevokeResponse: 吊销结果，包含吊销数量等信息

    Raises:
        HTTPException: 当 AIC 格式无效或没有找到相关证书时
    """
    # 验证 AIC 格式
    if not request.aic or len(request.aic) != 32:
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
        response = RevokeResponse(
            aic=request.aic,
            revocation_reason=reason_text,
            revoked_at=format_datetime(beijing_now()),
            revoked_cert_count=revoked_count,
        )

        return response

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to revoke certificates: {str(e)}",
        )
