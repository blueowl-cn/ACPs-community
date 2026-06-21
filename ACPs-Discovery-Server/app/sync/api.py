"""
DRC (Discovery Registry Coordination) 管理 API。

此模块提供用于监控和管理 DRC 同步服务的 API 端点。
"""

from datetime import datetime
from typing import Dict, Any, Optional
import json
import logging

from fastapi import APIRouter, HTTPException, status, Request, Header
from pydantic import BaseModel
from sqlmodel import select, delete

from .client import get_drc_client
from .exception import SyncException, SyncError
from .model import Agent, WebhookCreate, WebhookResponse, WebhookNotification
from .service import (
    process_webhook_notification, 
    verify_webhook_signature, 
    register_webhook_with_registry
)
from app.core.database import get_async_session
from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


class DRCStatus(BaseModel):
    """DRC 同步状态响应。"""

    is_running: bool
    last_seq: Optional[int]
    last_sync_time: Optional[datetime]
    needs_snapshot: bool
    object_count_by_type: Dict[str, int]
    sync_interval: int
    registry_url: str


class DRCControlResponse(BaseModel):
    """DRC 控制操作响应。"""

    success: bool
    message: str


@router.get("/status", response_model=DRCStatus)
async def get_drc_status():
    """获取当前 DRC 同步状态。"""
    try:
        client = get_drc_client()

        # 如果状态尚未初始化，创建默认状态
        if client.state is None:
            from .model import DRCState

            client.state = await DRCState.load_from_db()

        # 按类型计算对象数量
        object_count_by_type = {}
        for obj_type, objects in client.state.object_versions.items():
            object_count_by_type[obj_type] = len(objects)

        return DRCStatus(
            is_running=client.is_running,
            last_seq=client.state.last_seq,
            last_sync_time=client.state.last_sync_time,
            needs_snapshot=client.state.needs_snapshot,
            object_count_by_type=object_count_by_type,
            sync_interval=client.sync_interval,
            registry_url=client.registry_base_url,
        )
    except SyncException:
        raise
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.SYNC_FAIL,
            error_msg=f"获取DRC状态失败: {e}",
            input_params={},
        )


@router.post("/start", response_model=DRCControlResponse)
async def start_drc_sync_endpoint():
    """启动 DRC 同步服务。"""
    try:
        client = get_drc_client()
        await client.start_background_sync()
        return DRCControlResponse(success=True, message="DRC 同步启动成功")
    except SyncException:
        raise
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.SYNC_FAIL,
            error_msg=f"启动 DRC 同步失败: {e}",
            input_params={},
        )


@router.post("/stop", response_model=DRCControlResponse)
async def stop_drc_sync_endpoint():
    """停止 DRC 同步服务。"""
    try:
        client = get_drc_client()
        await client.stop_background_sync()
        return DRCControlResponse(success=True, message="DRC 同步停止成功")
    except SyncException:
        raise
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.SYNC_FAIL,
            error_msg=f"停止 DRC 同步失败: {e}",
            input_params={},
        )


@router.post("/sync", response_model=DRCControlResponse)
async def trigger_sync():
    """触发手动同步周期。"""
    try:
        client = get_drc_client()
        await client.sync_once()
        return DRCControlResponse(success=True, message="手动同步完成成功")
    except SyncException:
        raise
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.SYNC_FAIL,
            error_msg=f"手动同步失败: {e}",
            input_params={},
        )


@router.post("/reset", response_model=DRCControlResponse)
async def reset_sync_state():
    """重置内存中的 DRC 同步状态（强制下次同步时进行完整快照，没有清空数据库）。"""
    try:
        client = get_drc_client()
        client.state.last_seq = None
        client.state.object_versions.clear()
        client.state.needs_snapshot = True
        client.state.last_sync_time = None

        return DRCControlResponse(success=True, message="DRC 同步状态重置成功")
    except SyncException:
        raise
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.SYNC_FAIL,
            error_msg=f"重置同步状态失败: {e}",
            input_params={},
        )


@router.post("/hard-reset", response_model=DRCControlResponse)
async def hard_reset():
    """硬重置：清空所有Agent数据库数据并重置DRC同步状态，强制下次进行完整快照同步。"""
    try:
        client = get_drc_client()

        # 1. 重置内存中的同步状态
        client.state.last_seq = None
        client.state.object_versions.clear()
        client.state.needs_snapshot = True
        client.state.last_sync_time = None

        # 2. 清空数据库中的所有Agent数据
        async for session in get_async_session():
            # 删除所有Agent记录
            delete_stmt = delete(Agent)
            result = await session.execute(delete_stmt)
            deleted_count = result.rowcount

            # 提交事务
            await session.commit()
            break

        return DRCControlResponse(
            success=True,
            message=f"硬重置成功：已清空 {deleted_count} 条Agent记录并重置同步状态，下次同步将进行完整快照",
        )
    except SyncException:
        raise
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.SYNC_FAIL,
            error_msg=f"硬重置失败: {e}",
            input_params={},
        )


@router.get("/registry-info")
async def get_registry_info():
    """获取已连接的注册中心服务器信息。"""
    try:
        client = get_drc_client()
        info = await client.get_registry_info()

        if info is None:
            raise SyncException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                error_name=SyncError.REGISTRY_UNAVAILABLE,
                error_msg="无法连接到注册中心服务器",
                input_params={"registry_url": client.registry_base_url},
            )

        return info
    except SyncException:
        raise
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.REGISTRY_UNAVAILABLE,
            error_msg=f"获取注册中心信息时出错: {e}",
            input_params={},
        )


# Webhook相关端点

@router.post("/webhooks/receive")
async def receive_webhook(
    request: Request,
    x_webhook_id: str = Header(..., alias="X-Webhook-ID"),
    x_webhook_signature: str = Header(..., alias="X-Webhook-Signature"),
    x_webhook_timestamp: str = Header(..., alias="X-Webhook-Timestamp"),
):
    """接收来自Registry Server的webhook通知"""
    try:
        # 读取请求体
        body = await request.body()
        payload = body.decode('utf-8')
        
        # TODO: DRC WebHook客户端生成的密钥，临时用硬编码，后续需要修改
        secret = settings.DRC_WEBHOOK_SECRET 
        
        if not verify_webhook_signature(secret, x_webhook_timestamp, payload, x_webhook_signature):
            logger.warning(f"Webhook签名验证失败: {x_webhook_id}")
            raise HTTPException(status_code=401, detail="Invalid signature")
        
        # 解析通知数据
        notification_data = json.loads(payload)
        notification = WebhookNotification(**notification_data)
        print("="*40)
        print(notification.model_dump_json(indent=4))
        print("="*40)
        
        # 异步处理webhook通知
        await process_webhook_notification(notification)
        
        # TODO: 可能需要创建响应模型
        return {"status": "acknowledged", "processed_at": "2025-08-19T12:15:35Z"}

        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"处理webhook通知失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"处理webhook通知失败: {str(e)}"
        )


@router.post("/webhooks/register", response_model=WebhookResponse)
async def register_webhook(webhook_data: WebhookCreate):
    """
    向Registry Server注册webhook
    
    此端点会向Registry Server发送webhook注册请求，使Discovery Server能够接收数据变更通知。
    """
    try:
        result = await register_webhook_with_registry(webhook_data)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"注册webhook失败: {str(e)}"
        )
