"""
ACME 数据模型

定义 ACME 协议相关的数据库模型，包括账户、订单、授权、挑战、证书等。
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from sqlmodel import SQLModel, Field, Relationship, Column, JSON, Text
from app.common.certificate_model import CertificateStatus, RevocationReason
from app.common.time_utils import beijing_now, beijing_end_of_day


class AccountStatus(str, Enum):
    """账户状态枚举"""

    VALID = "valid"
    DEACTIVATED = "deactivated"
    REVOKED = "revoked"


class OrderStatus(str, Enum):
    """订单状态枚举"""

    PENDING = "pending"
    READY = "ready"
    PROCESSING = "processing"
    VALID = "valid"
    INVALID = "invalid"


class AuthorizationStatus(str, Enum):
    """授权状态枚举"""

    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    DEACTIVATED = "deactivated"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ChallengeStatus(str, Enum):
    """挑战状态枚举"""

    PENDING = "pending"
    PROCESSING = "processing"
    VALID = "valid"
    INVALID = "invalid"


class ChallengeType(str, Enum):
    """挑战类型枚举"""

    HTTP_01 = "http-01"


class AcmeAccount(SQLModel, table=True):
    """ACME 账户模型"""

    __tablename__ = "acme_accounts"

    id: Optional[int] = Field(default=None, primary_key=True)
    # ACME 账户的公钥指纹，用作唯一标识
    key_id: str = Field(unique=True, index=True, max_length=255)
    # JWK 格式的公钥
    public_key: str = Field(sa_column=Column(Text))
    # 账户状态
    status: AccountStatus = Field(default=AccountStatus.VALID)
    # 联系信息，通常是邮箱
    contact: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    # 是否同意服务条款
    terms_of_service_agreed: bool = Field(default=False)
    # 外部账户绑定信息
    external_account_binding: Optional[Dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON)
    )

    # 创建和更新时间
    created_at: datetime = Field(default_factory=beijing_now)
    updated_at: Optional[datetime] = Field(default=None)

    # 关系
    orders: List["AcmeOrder"] = Relationship(back_populates="account")


class AcmeOrder(SQLModel, table=True):
    """ACME 订单模型"""

    __tablename__ = "acme_orders"

    id: Optional[int] = Field(default=None, primary_key=True)
    # 订单的唯一标识符
    order_id: str = Field(unique=True, index=True, max_length=255)
    # 关联的账户ID
    account_id: int = Field(foreign_key="acme_accounts.id")
    # 订单状态
    status: OrderStatus = Field(default=OrderStatus.PENDING)
    # 要申请证书的标识符列表 (Agent IDs)
    identifiers: List[Dict[str, str]] = Field(sa_column=Column(JSON))
    # 证书有效期结束时间
    not_before: Optional[datetime] = Field(default=None)
    not_after: Optional[datetime] = Field(default=None)
    # 错误信息
    error: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    # 授权链接
    authorizations: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    # 完成链接
    finalize: Optional[str] = Field(default=None, max_length=512)
    # 证书链接
    certificate: Optional[str] = Field(default=None, max_length=512)

    # 创建和更新时间
    created_at: datetime = Field(default_factory=beijing_now)
    updated_at: Optional[datetime] = Field(default=None)
    expires: datetime = Field(default_factory=beijing_end_of_day)

    # 关系
    account: AcmeAccount = Relationship(back_populates="orders")
    authorizations_rel: List["AcmeAuthorization"] = Relationship(back_populates="order")


class AcmeAuthorization(SQLModel, table=True):
    """ACME 授权模型"""

    __tablename__ = "acme_authorizations"

    id: Optional[int] = Field(default=None, primary_key=True)
    # 授权的唯一标识符
    authz_id: str = Field(unique=True, index=True, max_length=255)
    # 关联的订单ID
    order_id: int = Field(foreign_key="acme_orders.id")
    # 要验证的标识符 (Agent ID)
    identifier: Dict[str, str] = Field(sa_column=Column(JSON))
    # 授权状态
    status: AuthorizationStatus = Field(default=AuthorizationStatus.PENDING)
    # 授权过期时间
    expires: datetime = Field(default_factory=beijing_end_of_day)
    # 是否为通配符授权
    wildcard: bool = Field(default=False)

    # 创建和更新时间
    created_at: datetime = Field(default_factory=beijing_now)
    updated_at: Optional[datetime] = Field(default=None)

    # 关系
    order: AcmeOrder = Relationship(back_populates="authorizations_rel")
    challenges: List["AcmeChallenge"] = Relationship(back_populates="authorization")


class AcmeChallenge(SQLModel, table=True):
    """ACME 挑战模型"""

    __tablename__ = "acme_challenges"

    id: Optional[int] = Field(default=None, primary_key=True)
    # 挑战的唯一标识符
    challenge_id: str = Field(unique=True, index=True, max_length=255)
    # 关联的授权ID
    authorization_id: int = Field(foreign_key="acme_authorizations.id")
    # 挑战类型
    type: ChallengeType = Field(default=ChallengeType.HTTP_01)
    # 挑战状态
    status: ChallengeStatus = Field(default=ChallengeStatus.PENDING)
    # 挑战令牌
    token: str = Field(max_length=255)
    # 验证的URL
    url: Optional[str] = Field(default=None, max_length=512)
    # 验证时间
    validated: Optional[datetime] = Field(default=None)
    # 错误信息
    error: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # 创建和更新时间
    created_at: datetime = Field(default_factory=beijing_now)
    updated_at: Optional[datetime] = Field(default=None)

    # 关系
    authorization: AcmeAuthorization = Relationship(back_populates="challenges")


class AcmeCertificate(SQLModel, table=True):
    """ACME 证书模型"""

    __tablename__ = "acme_certificates"

    id: Optional[int] = Field(default=None, primary_key=True)
    # 证书的唯一标识符
    cert_id: str = Field(unique=True, index=True, max_length=255)
    # 关联的订单ID
    order_id: int = Field(foreign_key="acme_orders.id")
    # 证书序列号
    serial_number: str = Field(unique=True, max_length=255)
    # PEM 格式的证书链
    certificate_pem: str = Field(sa_column=Column(Text))
    # 证书状态
    status: CertificateStatus = Field(default=CertificateStatus.VALID)
    # 证书主体信息
    subject: Dict[str, Any] = Field(sa_column=Column(JSON))
    # 证书有效期
    not_before: datetime
    not_after: datetime
    # 吊销信息
    revoked_at: Optional[datetime] = Field(default=None)
    revocation_reason: Optional[RevocationReason] = Field(default=None)
    # Agent Identity Code - 用于批量吊销
    aic: Optional[str] = Field(default=None, index=True, max_length=255)

    # 创建和更新时间
    created_at: datetime = Field(default_factory=beijing_now)
    updated_at: Optional[datetime] = Field(default=None)


class AcmeNonce(SQLModel, table=True):
    """ACME Nonce 模型"""

    __tablename__ = "acme_nonces"

    id: Optional[int] = Field(default=None, primary_key=True)
    # Nonce 值
    nonce: str = Field(unique=True, index=True, max_length=255)
    # 是否已使用
    used: bool = Field(default=False)
    # 过期时间
    expires: datetime = Field(
        default_factory=lambda: beijing_now().replace(
            minute=59, second=59, microsecond=0
        )
    )

    # 创建时间
    created_at: datetime = Field(default_factory=beijing_now)
