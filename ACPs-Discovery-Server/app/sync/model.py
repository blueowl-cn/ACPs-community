"""
DRC (Discovery Registry Coordination) 数据模型。

此模块定义 DRC 协议中用于注册中心和发现服务之间数据同步的数据结构。
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField, JSON, Column
from sqlalchemy import String, Integer, BigInteger, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB


class OperationType(str, Enum):
    """DRC 操作类型。"""

    UPSERT = "upsert"
    DELETE = "delete"


class PayloadType(str, Enum):
    """DRC 载荷类型。"""

    FULL_OBJ = "FULL_OBJ"
    OBJ_PATCH = "OBJ_PATCH"


class Envelope(BaseModel):
    """
    所有数据传输的 DRC 信封结构。

    所有传输的数据都使用这种统一的信封结构来确保幂等性和演化能力。
    """

    seq: int = Field(..., description="全局递增序列号")
    ts: Optional[datetime] = Field(None, description="变更时间戳")
    op: Optional[OperationType] = Field(
        default=OperationType.UPSERT,
        description="操作类型：upsert（默认）或 delete",
    )
    type: str = Field(..., description="对象类型（例如：acs、dataset、file、user）")
    id: str = Field(..., description="对象全局唯一标识符")
    version: int = Field(
        ...,
        description="对象版本号，在单个对象内单调递增",
    )
    payload: Optional[Dict[str, Any]] = Field(None, description="实际数据内容")


class DRCState(BaseModel):
    """
    用于跟踪同步进度的 DRC 客户端状态。
    """

    last_seq: Optional[int] = Field(None, description="最后处理的序列号")
    object_versions: Dict[str, Dict[str, int]] = Field(
        default_factory=dict,
        description="按类型和 ID 分组的对象版本：{type: {id: version}}",
    )
    last_sync_time: Optional[datetime] = Field(None, description="最后同步时间")
    needs_snapshot: bool = Field(True, description="是否需要完整快照")

    @classmethod
    async def load_from_db(cls) -> "DRCState":
        """从数据库加载同步状态"""
        try:
            # 查询数据库中的最大 seq 作为 last_seq
            from app.core.database import get_async_session
            from sqlmodel import select, func

            async for session in get_async_session():
                result = await session.execute(select(func.max(Agent.seq)))
                max_seq = result.scalar()

                if max_seq:
                    # 如果数据库中有数据，说明之前已经同步过
                    return cls(
                        last_seq=max_seq,
                        needs_snapshot=False,  # 有历史数据时不需要全量同步
                    )
                else:
                    # 数据库为空，需要全量同步
                    return cls()
                break
        except Exception:
            # 出错时使用默认状态
            return cls()


class SnapshotResponseHeader(BaseModel):
    """快照 API 的响应头信息。"""

    snapshot_id: str
    snapshot_seq: int
    chunk_index: int
    chunk_total: int
    object_count: int


class ChangesResponseHeader(BaseModel):
    """变更 API 的响应头信息。"""

    next_seq: int


class RegistryInfo(BaseModel):
    """来自信息 API 的注册中心服务器信息。"""

    service: str
    version: str
    build: Optional[str] = None
    status: str
    supported_types: list[str]
    retention: Optional[Dict[str, Any]] = None
    snapshot: Optional[Dict[str, Any]] = None
    changes: Optional[Dict[str, Any]] = None


class WebhookNotification(BaseModel):
    """Webhook通知的数据结构"""
    # TODO: webhook_id改为id，跟手册保持一致
    webhook_id: str = Field(..., description="Webhook ID")
    event: str = Field(..., description="事件类型")
    timestamp: str = Field(..., description="时间戳")
    data: Dict[str, Any] = Field(..., description="事件数据")


class WebhookCreate(BaseModel):
    """创建Webhook的请求模型"""
    
    url: str = Field(..., description="回调URL")
    secret: str = Field(..., description="签名密钥")
    types: list[str] = Field(default=["acs"], description="关注的数据类型列表")
    events: list[str] = Field(default=["data_change"], description="关注的事件类型列表")
    description: Optional[str] = Field(default=None, description="Webhook描述")

class WebhookResponse(BaseModel):
    """Webhook响应模型"""
    
    id: str = Field(..., description="Webhook ID")
    url: str = Field(..., description="回调URL")
    types: list[str] = Field(..., description="关注的数据类型列表")
    events: list[str] = Field(..., description="关注的事件类型列表")
    description: Optional[str] = Field(default=None, description="Webhook描述")
    status: str = Field(..., description="Webhook状态")
    failure_count: int = Field(..., description="失败计数")
    last_triggered_at: Optional[datetime] = Field(default=None, description="最后触发时间")
    last_success_at: Optional[datetime] = Field(default=None, description="最后成功时间")
    last_failure_at: Optional[datetime] = Field(default=None, description="最后失败时间")
    next_retry_at: Optional[datetime] = Field(default=None, description="下次重试时间")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

# TODO: 跟文档Envelope对比缺少字段
class Agent(SQLModel, table=True):
    """
    Agent 数据库模型，用于存储从 Registry 同步的 Agent 数据。

    对应 DRC 协议中的 Envelope 数据结构，存储同步过来的 ACS 对象。
    """

    __tablename__ = "agents"

    # 对应 Envelope.id - Agent 的唯一标识符
    aic: str = SQLField(
        sa_column=Column(String(255), primary_key=True, nullable=False),
        description="Agent 唯一标识符，对应 Envelope.id",
    )

    # 对应 Envelope.version - 版本号
    version: int = SQLField(
        sa_column=Column(Integer, nullable=False),
        description="Agent 版本号，对应 Envelope.version",
    )

    # 对应 Envelope.seq - 同步序列号
    seq: int = SQLField(
        sa_column=Column(BigInteger, nullable=False),
        description="同步序列号，对应 Envelope.seq",
    )

    # 对应 Envelope.payload - ACS 数据
    acs: Optional[Dict[str, Any]] = SQLField(
        default=None,
        sa_column=Column(JSONB, nullable=True),
        description="ACS 数据，对应 Envelope.payload",
    )

    class Config:
        from_attributes = True