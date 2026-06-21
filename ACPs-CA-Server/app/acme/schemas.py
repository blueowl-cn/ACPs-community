"""
ACME 数据模式

定义 ACME 协议的 Pydantic 数据验证模型，用于 API 请求和响应的序列化/反序列化。
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from .models import (
    AccountStatus,
    OrderStatus,
    AuthorizationStatus,
    ChallengeStatus,
    ChallengeType,
)


# ================== 通用模式 ==================


class ACMEErrorDetail(BaseModel):
    """ACME 错误详情"""

    type: str = Field(..., description="错误类型URI")
    detail: str = Field(..., description="错误详细描述")
    instance: Optional[str] = Field(None, description="错误实例标识")


class JWKKey(BaseModel):
    """JSON Web Key 模式"""

    kty: str = Field(..., description="密钥类型，如 RSA")
    use: Optional[str] = Field(None, description="密钥用途")
    alg: Optional[str] = Field(None, description="算法")
    n: Optional[str] = Field(None, description="RSA 模数")
    e: Optional[str] = Field(None, description="RSA 指数")
    # 可以根据需要添加其他密钥参数


class JWSHeader(BaseModel):
    """JWS 头部"""

    alg: str = Field(..., description="签名算法")
    nonce: str = Field(..., description="随机数")
    url: str = Field(..., description="请求URL")
    jwk: Optional[JWKKey] = Field(None, description="JSON Web Key")
    kid: Optional[str] = Field(None, description="密钥ID")


class JWSRequest(BaseModel):
    """JWS 请求格式"""

    protected: str = Field(..., description="Base64URL 编码的头部")
    payload: str = Field(..., description="Base64URL 编码的载荷")
    signature: str = Field(..., description="Base64URL 编码的签名")


# ================== 目录服务 ==================


class ACMEDirectory(BaseModel):
    """ACME 目录响应"""

    newNonce: str = Field(..., description="获取新 nonce 的端点")
    newAccount: str = Field(..., description="创建新账户的端点")
    newOrder: str = Field(..., description="创建新订单的端点")
    newAuthz: Optional[str] = Field(None, description="预授权端点")
    revokeCert: str = Field(..., description="吊销证书的端点")
    keyChange: str = Field(..., description="密钥更换的端点")
    meta: Optional[Dict[str, Any]] = Field(None, description="元数据信息")


# ================== 账户管理 ==================


class NewAccountRequest(BaseModel):
    """新建账户请求"""

    termsOfServiceAgreed: bool = Field(..., description="是否同意服务条款")
    contact: Optional[List[str]] = Field(None, description="联系方式列表")
    onlyReturnExisting: Optional[bool] = Field(False, description="仅返回已存在的账户")
    externalAccountBinding: Optional[Dict[str, Any]] = Field(
        None, description="外部账户绑定"
    )


class AccountUpdateRequest(BaseModel):
    """账户更新请求"""

    contact: Optional[List[str]] = Field(None, description="联系方式列表")
    status: Optional[AccountStatus] = Field(None, description="账户状态")


class AccountResponse(BaseModel):
    """账户响应"""

    model_config = ConfigDict(from_attributes=True)

    status: AccountStatus = Field(..., description="账户状态")
    contact: Optional[List[str]] = Field(None, description="联系方式列表")
    termsOfServiceAgreed: Optional[bool] = Field(None, description="是否同意服务条款")
    orders: str = Field(..., description="订单列表链接")
    created_at: datetime = Field(..., description="创建时间")


# ================== 订单管理 ==================


class IdentifierInput(BaseModel):
    """标识符输入"""

    type: str = Field(..., description="标识符类型，Agent CA中为'agent'")
    value: str = Field(..., description="标识符值，即Agent ID")


class NewOrderRequest(BaseModel):
    """新建订单请求"""

    identifiers: List[IdentifierInput] = Field(
        ..., description="要申请证书的标识符列表"
    )
    notBefore: Optional[datetime] = Field(None, description="证书生效时间")
    notAfter: Optional[datetime] = Field(None, description="证书失效时间")


class OrderResponse(BaseModel):
    """订单响应"""

    model_config = ConfigDict(from_attributes=True)

    status: OrderStatus = Field(..., description="订单状态")
    expires: datetime = Field(..., description="订单过期时间")
    identifiers: List[Dict[str, str]] = Field(..., description="标识符列表")
    notBefore: Optional[datetime] = Field(None, description="证书生效时间")
    notAfter: Optional[datetime] = Field(None, description="证书失效时间")
    error: Optional[ACMEErrorDetail] = Field(None, description="错误信息")
    authorizations: List[str] = Field(..., description="授权链接列表")
    finalize: str = Field(..., description="完成链接")
    certificate: Optional[str] = Field(None, description="证书链接")


class FinalizeOrderRequest(BaseModel):
    """完成订单请求"""

    csr: str = Field(..., description="Base64URL 编码的 DER 格式 CSR")


# ================== 授权管理 ==================


class AuthorizationResponse(BaseModel):
    """授权响应"""

    model_config = ConfigDict(from_attributes=True)

    identifier: Dict[str, str] = Field(..., description="要验证的标识符")
    status: AuthorizationStatus = Field(..., description="授权状态")
    expires: datetime = Field(..., description="过期时间")
    challenges: List[Dict[str, Any]] = Field(..., description="挑战列表")
    wildcard: Optional[bool] = Field(None, description="是否为通配符授权")


# ================== 挑战验证 ==================


class ChallengeResponse(BaseModel):
    """挑战响应"""

    model_config = ConfigDict(from_attributes=True)

    type: ChallengeType = Field(..., description="挑战类型")
    url: str = Field(..., description="挑战URL")
    status: ChallengeStatus = Field(..., description="挑战状态")
    token: str = Field(..., description="挑战令牌")
    validated: Optional[datetime] = Field(None, description="验证时间")
    error: Optional[ACMEErrorDetail] = Field(None, description="错误信息")


class HTTP01Challenge(ChallengeResponse):
    """HTTP-01 挑战"""

    type: ChallengeType = Field(ChallengeType.HTTP_01, description="挑战类型")


class ChallengeRequest(BaseModel):
    """挑战请求"""

    # 空对象，表示准备好进行验证
    pass


# ================== 证书管理 ==================


class CertificateResponse(BaseModel):
    """证书响应 - 返回 PEM 格式的证书链"""

    certificate_chain: str = Field(..., description="PEM 格式的证书链")


class RevokeCertificateRequest(BaseModel):
    """吊销证书请求"""

    certificate: str = Field(..., description="Base64URL 编码的 DER 格式证书")
    reason: Optional[int] = Field(None, description="吊销原因代码")


# ================== 密钥更换 ==================


class KeyChangeRequest(BaseModel):
    """密钥更换请求"""

    account: str = Field(..., description="账户URL")
    oldKey: JWKKey = Field(..., description="旧密钥")


# ================== 内部使用的数据传输对象 ==================


class AccountCreate(BaseModel):
    """内部账户创建DTO"""

    key_id: str
    public_key: str
    contact: Optional[List[str]] = None
    terms_of_service_agreed: bool = False
    external_account_binding: Optional[Dict[str, Any]] = None


class OrderCreate(BaseModel):
    """内部订单创建DTO"""

    account_id: int
    identifiers: List[Dict[str, str]]
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None


class AuthorizationCreate(BaseModel):
    """内部授权创建DTO"""

    order_id: int
    identifier: Dict[str, str]
    expires: datetime


class ChallengeCreate(BaseModel):
    """内部挑战创建DTO"""

    authorization_id: int
    type: ChallengeType
    token: str


class CertificateCreate(BaseModel):
    """内部证书创建DTO"""

    order_id: int
    serial_number: str
    certificate_pem: str
    subject: Dict[str, Any]
    not_before: datetime
    not_after: datetime
    aic: Optional[str] = None  # Agent Identity Code


# ================== HTTP 验证相关 ==================


class AgentValidationInfo(BaseModel):
    """Agent 验证信息"""

    agent_id: str = Field(..., description="Agent ID")
    endpoint: str = Field(..., description="Agent HTTP 端点")
    validation_path: str = Field(..., description="验证路径模板")


class ValidationRequest(BaseModel):
    """验证请求"""

    token: str = Field(..., description="挑战令牌")
    key_authorization: str = Field(..., description="密钥授权")
    agent_endpoint: str = Field(..., description="Agent 端点")
    agent_id: str = Field(..., description="Agent ID")


class ValidationResponse(BaseModel):
    """验证响应"""

    success: bool = Field(..., description="验证是否成功")
    error: Optional[str] = Field(None, description="错误信息")
    response_content: Optional[str] = Field(None, description="实际响应内容")
    expected_content: Optional[str] = Field(None, description="期望响应内容")
