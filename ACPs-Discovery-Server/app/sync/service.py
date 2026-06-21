"""
Webhook服务模块

处理来自Registry Server的webhook通知，并管理webhook注册。
"""

import hashlib
import hmac
import logging
from typing import Dict, Any

import httpx
from fastapi import HTTPException, status

from .model import WebhookNotification, WebhookCreate, WebhookResponse
from app.core.config import settings
from app.sync.client import get_drc_client

logger = logging.getLogger(__name__)


def verify_webhook_signature(
    secret: str, 
    timestamp: str, 
    payload: str, 
    signature: str
) -> bool:
    """
    验证webhook签名
    
    Args:
        secret: 签名密钥
        timestamp: 时间戳
        payload: 请求体
        signature: 签名
        
    Returns:
        签名是否有效
    """
    try:
        # 构建签名字符串
        message = f"{timestamp}.{payload}"
        
        # 计算HMAC-SHA256签名
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # 比较签名
        return hmac.compare_digest(f"sha256={expected_signature}", signature)
    except Exception as e:
        logger.error(f"验证webhook签名失败: {e}")
        return False


async def process_webhook_notification(notification: WebhookNotification) -> None:
    """
    处理webhook通知
    
    Args:
        notification: webhook通知数据
    """
    try:
        logger.info(f"收到webhook通知: {notification.event}")
        
        # 统一使用一个handler处理所有事件
        await handle_webhook_event(notification.event, notification.data)
            
    except Exception as e:
        logger.error(f"处理webhook通知失败: {e}")


async def handle_webhook_event(event_type: str, data: Dict[str, Any]) -> None:
    """
    统一处理所有webhook事件
    
    Args:
        event_type: 事件类型
        data: 事件数据
    """
    try:
        logger.info(f"处理webhook事件: {event_type}, 数据: {data}")
        
        # 触发DRC同步
        client = get_drc_client()
        await client.sync_once()
        
    except Exception as e:
        logger.error(f"处理webhook事件失败: {e}")


async def register_webhook_with_registry(webhook_data: WebhookCreate) -> WebhookResponse:
    """
    向Registry Server注册webhook
    
    Args:
        webhook_data: webhook创建数据
        
    Returns:
        注册结果
    """
    try:
        client = get_drc_client()
        registry_url = client.registry_base_url
        
        # 构建注册请求
        register_data = {
            "url": settings.DRC_WEBHOOK_RECEIVE_URL,  # 使用配置中的URL
            "secret": webhook_data.secret,
            "types": webhook_data.types,
            "events": webhook_data.events,
            "description": webhook_data.description or "Discovery Server自动注册的webhook"
        }
        # 发送注册请求
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                f"{registry_url}/webhooks",  # 添加正确的API路径
                json=register_data,
                timeout=30.0
            )
            
            if response.status_code == 201:
                result = response.json()
                logger.info(f"成功向Registry注册webhook: {result.get('id')}")
                return WebhookResponse(**result)
            else:
                logger.error(f"向Registry注册webhook失败: {response.status_code} {response.text}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"向Registry注册webhook失败: {response.text}"
                )
                
    except Exception as e:
        logger.error(f"注册webhook时出错: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"注册webhook失败: {str(e)}"
        )
