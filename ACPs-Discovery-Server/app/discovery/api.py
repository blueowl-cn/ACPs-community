"""
发现 API 端点。

此模块包含 Agent 发现功能的 FastAPI 路由和端点定义。
"""
import logging
from fastapi import APIRouter

from app.discovery.schema import DiscoveryRequest, DiscoveryResponse
from app.discovery.service import discovery_service

# 创建路由器
router = APIRouter()
logger = logging.getLogger(__name__)

@router.post(
    "/",
    response_model=DiscoveryResponse,
    summary="发现 Agent（POST 方法）",
    description="基于自然语言查询使用 POST 方法发现 Agent",
)
async def discover_agents_post(request: DiscoveryRequest) -> DiscoveryResponse:
    """
    基于自然语言查询发现 Agent（POST 方法）。

    此端点接受请求体中的自然语言查询，
    并返回匹配的 Agent 列表及其能力和技能。
    """
    return await discovery_service.discover_agents_async(request)
