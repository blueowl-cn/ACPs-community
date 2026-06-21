"""
证书相关的数据模型
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from sqlmodel import SQLModel, Field
from uuid6 import uuid7

from .time_utils import beijing_now


class CertificateStatus(str, Enum):
    """证书状态枚举 - 统一的证书状态定义"""

    PENDING = "pending"  # 待签发
    VALID = "valid"  # 有效
    REVOKED = "revoked"  # 已吊销
    EXPIRED = "expired"  # 已过期


class RevocationReason(str, Enum):
    """证书吊销原因枚举 - 遵循 RFC 5280 标准"""

    UNSPECIFIED = "unspecified"  # 0 - 未指定
    KEY_COMPROMISE = "keyCompromise"  # 1 - 密钥泄露
    CA_COMPROMISE = "caCompromise"  # 2 - CA 密钥泄露
    AFFILIATION_CHANGED = "affiliationChanged"  # 3 - 归属变更
    SUPERSEDED = "superseded"  # 4 - 已被替代
    CESSATION_OF_OPERATION = "cessationOfOperation"  # 5 - 停止操作

    @classmethod
    def from_acme_code(cls, code: int) -> "RevocationReason":
        """从ACME吊销代码转换为吊销原因"""
        mapping = {
            0: cls.UNSPECIFIED,
            1: cls.KEY_COMPROMISE,
            2: cls.CA_COMPROMISE,
            3: cls.AFFILIATION_CHANGED,
            4: cls.SUPERSEDED,
            5: cls.CESSATION_OF_OPERATION,
        }
        return mapping.get(code, cls.UNSPECIFIED)

    def to_acme_code(self) -> int:
        """转换为ACME吊销代码"""
        mapping = {
            self.UNSPECIFIED: 0,
            self.KEY_COMPROMISE: 1,
            self.CA_COMPROMISE: 2,
            self.AFFILIATION_CHANGED: 3,
            self.SUPERSEDED: 4,
            self.CESSATION_OF_OPERATION: 5,
        }
        return mapping.get(self, 0)


class CertificateType(str, Enum):
    """证书类型枚举"""

    ROOT = "root"  # 根证书
    INTERMEDIATE = "intermediate"  # 中间证书
    USER = "user"  # 用户证书
    AGENT = "agent"  # Agent证书（ACME协议签发）


class Certificate(SQLModel, table=True):
    """证书数据模型"""

    __tablename__ = "certificates"

    # 基本字段
    id: UUID = Field(default_factory=uuid7, primary_key=True)
    certificate_type: CertificateType = Field(description="证书类型")
    serial_number: str = Field(unique=True, index=True, description="证书序列号")
    subject: str = Field(description="证书主体")
    issuer: str = Field(description="签发者")

    # 状态和时间
    status: CertificateStatus = Field(
        default=CertificateStatus.PENDING, description="证书状态"
    )
    issued_at: datetime = Field(default_factory=beijing_now, description="签发时间")
    expires_at: datetime = Field(description="过期时间")
    revoked_at: Optional[datetime] = Field(default=None, description="吊销时间")
    revocation_reason: Optional[RevocationReason] = Field(
        default=None, description="吊销原因"
    )

    # 证书内容
    certificate_pem: str = Field(description="证书PEM格式内容")
    public_key: str = Field(description="公钥")
    
    # 版本号，自增量，用于区分同一AIC的不同版本证书
    version: int = Field(default=1, description="证书版本号")

    # 关联字段
    parent_certificate_id: Optional[UUID] = Field(
        default=None, foreign_key="certificates.id", description="父证书ID"
    )
    aic: Optional[str] = Field(
        default=None, index=True, description="Agent Identify Code"
    )

    # 元数据
    created_at: datetime = Field(default_factory=beijing_now, description="创建时间")
    updated_at: datetime = Field(default_factory=beijing_now, description="更新时间")
