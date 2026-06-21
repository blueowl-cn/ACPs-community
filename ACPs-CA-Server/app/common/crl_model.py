"""
CRL (Certificate Revocation List) 相关的数据模型
"""

from datetime import datetime
from enum import Enum
from typing import List
from uuid import UUID

from sqlmodel import SQLModel, Field, JSON, Column
from uuid6 import uuid7

from .time_utils import beijing_now
from .certificate_model import RevocationReason


class CRLStatus(str, Enum):
    """CRL状态枚举"""

    CURRENT = "current"  # 当前有效
    SUPERSEDED = "superseded"  # 已被取代
    EXPIRED = "expired"  # 已过期


class CRL(SQLModel, table=True):
    """CRL数据模型"""

    __tablename__ = "certificate_revocation_lists"

    # 基本字段
    id: UUID = Field(default_factory=uuid7, primary_key=True)
    version: str = Field(unique=True, index=True, description="CRL版本号 YYYYMMDDHH")
    crl_number: int = Field(description="CRL编号，单调递增")

    # CRL内容
    issuer: str = Field(description="CRL签发者")
    this_update: datetime = Field(description="本次更新时间")
    next_update: datetime = Field(description="下次更新时间")

    # CRL状态
    status: CRLStatus = Field(default=CRLStatus.CURRENT, description="CRL状态")

    # 吊销证书列表
    revoked_certificates_count: int = Field(default=0, description="吊销证书数量")

    # CRL文件内容
    crl_der: bytes = Field(description="DER格式的CRL内容")
    crl_pem: str = Field(description="PEM格式的CRL内容")
    crl_size: int = Field(description="CRL文件大小（字节）")

    # 分发信息
    distribution_points: List[str] = Field(
        sa_column=Column(JSON), description="CRL分发点列表"
    )

    # 签名信息
    signature_algorithm: str = Field(description="签名算法")
    signature_key_id: str = Field(description="签名密钥ID")

    # 元数据
    created_at: datetime = Field(default_factory=beijing_now, description="创建时间")


class RevokedCertificateEntry(SQLModel, table=True):
    """CRL中的吊销证书条目"""

    __tablename__ = "revoked_certificate_entries"

    # 基本字段
    id: UUID = Field(default_factory=uuid7, primary_key=True)
    crl_id: UUID = Field(
        foreign_key="certificate_revocation_lists.id", description="CRL ID"
    )

    # 证书信息
    serial_number: str = Field(index=True, description="证书序列号")
    revocation_date: datetime = Field(description="吊销时间")
    revocation_reason: RevocationReason = Field(description="吊销原因")

    # 元数据
    created_at: datetime = Field(default_factory=beijing_now, description="创建时间")
