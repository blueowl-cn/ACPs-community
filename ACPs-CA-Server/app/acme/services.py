"""
ACME 业务逻辑服务

实现 ACME 协议的核心业务逻辑，包括账户管理、订单处理、授权验证、证书签发等。
"""

import secrets
import base64
from datetime import timedelta
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.backends import default_backend
from sqlmodel import Session, select

from app.core.db_session import get_session
from app.core.ca_manager import get_ca_manager
from app.core.config import get_settings
from app.common import Certificate, CertificateType, CertificateStatus
from app.common.time_utils import beijing_now
from .jws_verifier import get_jws_verifier

if TYPE_CHECKING:
    from .agent_registry import AgentInfo
from .models import (
    AcmeAccount,
    AcmeOrder,
    AcmeAuthorization,
    AcmeChallenge,
    AcmeCertificate,
    AcmeNonce,
    OrderStatus,
    AuthorizationStatus,
    ChallengeStatus,
    CertificateStatus,
    RevocationReason,
)
from .schemas import (
    AccountCreate,
    OrderCreate,
    AuthorizationCreate,
    ChallengeCreate,
    CertificateCreate,
)
from .exception import AcmeException, AcmeError


class NonceService:
    """Nonce 管理服务"""

    def __init__(self, session: Session):
        self.session = session

    def generate_nonce(self) -> str:
        """生成新的 nonce"""
        # 生成32字节的随机数据并转为 base64url
        random_bytes = secrets.token_bytes(32)
        nonce = base64.urlsafe_b64encode(random_bytes).decode("ascii").rstrip("=")

        # 保存到数据库
        nonce_obj = AcmeNonce(nonce=nonce)
        self.session.add(nonce_obj)
        self.session.commit()

        return nonce

    def validate_and_consume_nonce(self, nonce: str) -> bool:
        """验证并消费 nonce"""
        statement = select(AcmeNonce).where(
            AcmeNonce.nonce == nonce,
            AcmeNonce.used == False,
            AcmeNonce.expires > beijing_now(),
        )
        nonce_obj = self.session.exec(statement).first()

        if not nonce_obj:
            return False

        # 标记为已使用
        nonce_obj.used = True
        self.session.add(nonce_obj)
        self.session.commit()

        return True

    def cleanup_expired_nonces(self):
        """清理过期的 nonce"""
        statement = select(AcmeNonce).where(AcmeNonce.expires <= beijing_now())
        expired_nonces = self.session.exec(statement).all()

        for nonce in expired_nonces:
            self.session.delete(nonce)

        self.session.commit()


class JWKService:
    """JSON Web Key 处理服务"""

    @staticmethod
    def compute_jwk_thumbprint(jwk: Dict[str, Any]) -> str:
        """计算 JWK 指纹"""
        jws_verifier = get_jws_verifier()
        return jws_verifier.compute_jwk_thumbprint(jwk)

    @staticmethod
    def create_key_authorization(token: str, jwk: Dict[str, Any]) -> str:
        """创建密钥授权字符串"""
        thumbprint = JWKService.compute_jwk_thumbprint(jwk)
        return f"{token}.{thumbprint}"

    @staticmethod
    def verify_jws_request(
        jws_data: str,
        public_key_jwk: Dict[str, Any],
        expected_nonce: Optional[str] = None,
        expected_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """验证 JWS 请求"""
        jws_verifier = get_jws_verifier()
        return jws_verifier.verify_jws_signature(
            jws_data, public_key_jwk, expected_nonce, expected_url
        )


class AccountService:
    """账户管理服务"""

    def __init__(self, session: Session):
        self.session = session

    def create_account(self, account_data: AccountCreate) -> AcmeAccount:
        """创建新账户或返回现有账户"""
        # 检查账户是否已存在
        statement = select(AcmeAccount).where(AcmeAccount.key_id == account_data.key_id)
        existing_account = self.session.exec(statement).first()

        if existing_account:
            # 根据ACME RFC，返回现有账户而不是错误
            return existing_account

        account = AcmeAccount(
            key_id=account_data.key_id,
            public_key=account_data.public_key,
            contact=account_data.contact,
            terms_of_service_agreed=account_data.terms_of_service_agreed,
            external_account_binding=account_data.external_account_binding,
        )

        self.session.add(account)
        self.session.commit()
        self.session.refresh(account)

        return account

    def get_account_by_key_id(self, key_id: str) -> Optional[AcmeAccount]:
        """根据密钥ID获取账户"""
        statement = select(AcmeAccount).where(AcmeAccount.key_id == key_id)
        return self.session.exec(statement).first()

    def get_account_by_id(self, account_id: int) -> Optional[AcmeAccount]:
        """根据ID获取账户"""
        statement = select(AcmeAccount).where(AcmeAccount.id == account_id)
        return self.session.exec(statement).first()

    def update_account(self, account: AcmeAccount, **kwargs) -> AcmeAccount:
        """更新账户信息"""
        for key, value in kwargs.items():
            if hasattr(account, key):
                setattr(account, key, value)

        account.updated_at = beijing_now()
        self.session.add(account)
        self.session.commit()
        self.session.refresh(account)

        return account


class OrderService:
    """订单管理服务"""

    def __init__(self, session: Session):
        self.session = session

    def create_order(self, order_data: OrderCreate) -> AcmeOrder:
        """创建新订单"""
        order_id = self._generate_order_id()

        order = AcmeOrder(
            order_id=order_id,
            account_id=order_data.account_id,
            identifiers=order_data.identifiers,
            not_before=order_data.not_before,
            not_after=order_data.not_after,
            expires=beijing_now() + timedelta(days=1),  # 订单24小时过期
        )

        self.session.add(order)
        self.session.commit()
        self.session.refresh(order)

        return order

    def get_order_by_id(self, order_id: str) -> Optional[AcmeOrder]:
        """根据订单ID获取订单"""
        statement = select(AcmeOrder).where(AcmeOrder.order_id == order_id)
        return self.session.exec(statement).first()

    def get_order_by_pk(self, order_pk: int) -> Optional[AcmeOrder]:
        """根据订单主键获取订单"""
        statement = select(AcmeOrder).where(AcmeOrder.id == order_pk)
        return self.session.exec(statement).first()

    def update_order_status(self, order: AcmeOrder, status: OrderStatus) -> AcmeOrder:
        """更新订单状态"""
        order.status = status
        order.updated_at = beijing_now()
        self.session.add(order)
        self.session.commit()
        self.session.refresh(order)

        return order

    def _generate_order_id(self) -> str:
        """生成订单ID"""
        return f"order_{secrets.token_urlsafe(16)}"


class AuthorizationService:
    """授权管理服务"""

    def __init__(self, session: Session):
        self.session = session

    def create_authorization(self, auth_data: AuthorizationCreate) -> AcmeAuthorization:
        """创建授权"""
        authz_id = self._generate_authz_id()

        authorization = AcmeAuthorization(
            authz_id=authz_id,
            order_id=auth_data.order_id,
            identifier=auth_data.identifier,
            expires=auth_data.expires,
        )

        self.session.add(authorization)
        self.session.commit()
        self.session.refresh(authorization)

        return authorization

    def get_authorization_by_id(self, authz_id: str) -> Optional[AcmeAuthorization]:
        """根据授权ID获取授权"""
        statement = select(AcmeAuthorization).where(
            AcmeAuthorization.authz_id == authz_id
        )
        return self.session.exec(statement).first()

    def get_authorizations_by_order_id(self, order_id: int) -> List[AcmeAuthorization]:
        """根据订单ID获取所有授权"""
        statement = select(AcmeAuthorization).where(
            AcmeAuthorization.order_id == order_id
        )
        return list(self.session.exec(statement).all())

    def update_authorization_status(
        self, authorization: AcmeAuthorization, status: AuthorizationStatus
    ) -> AcmeAuthorization:
        """更新授权状态"""
        authorization.status = status
        authorization.updated_at = beijing_now()
        self.session.add(authorization)
        self.session.commit()
        self.session.refresh(authorization)

        return authorization

    def _generate_authz_id(self) -> str:
        """生成授权ID"""
        return f"authz_{secrets.token_urlsafe(16)}"


class ChallengeService:
    """挑战管理服务"""

    def __init__(self, session: Session):
        self.session = session

    def create_challenge(self, challenge_data: ChallengeCreate) -> AcmeChallenge:
        """创建挑战"""
        challenge_id = self._generate_challenge_id()

        challenge = AcmeChallenge(
            challenge_id=challenge_id,
            authorization_id=challenge_data.authorization_id,
            type=challenge_data.type,
            token=challenge_data.token,
        )

        self.session.add(challenge)
        self.session.commit()
        self.session.refresh(challenge)

        return challenge

    def get_challenge_by_id(self, challenge_id: str) -> Optional[AcmeChallenge]:
        """根据挑战ID获取挑战"""
        statement = select(AcmeChallenge).where(
            AcmeChallenge.challenge_id == challenge_id
        )
        return self.session.exec(statement).first()

    def update_challenge_status(
        self,
        challenge: AcmeChallenge,
        status: ChallengeStatus,
        error: Optional[Dict[str, Any]] = None,
    ) -> AcmeChallenge:
        """更新挑战状态"""
        challenge.status = status
        challenge.updated_at = beijing_now()

        if status == ChallengeStatus.VALID:
            challenge.validated = beijing_now()

        if error:
            challenge.error = error

        self.session.add(challenge)
        self.session.commit()
        self.session.refresh(challenge)

        return challenge

    def _generate_challenge_id(self) -> str:
        """生成挑战ID"""
        return f"challenge_{secrets.token_urlsafe(16)}"


# 注释：旧的ValidationService已被HTTP01ValidationService替代
# class ValidationService:
#     """验证服务"""
#     ... (已移除，使用app.acme.http01_validator中的HTTP01ValidationService)


class CertificateService:
    """证书管理服务"""

    def __init__(self, session: Session):
        self.session = session
        self.settings = get_settings()

    def issue_certificate(
        self, order: AcmeOrder, csr_der: bytes, agent_infos: List["AgentInfo"] = None
    ) -> List[AcmeCertificate]:
        """签发证书 - 支持为每个Agent分别签发证书

        Args:
            order: ACME订单
            csr_der: DER格式的CSR
            agent_infos: Agent信息列表，用于构造证书DN

        Returns:
            List[AcmeCertificate]: 签发的证书列表（每个Agent一张证书）
        """
        # 解析 CSR
        csr = x509.load_der_x509_csr(csr_der)

        # 验证 CSR 中的主体名称与订单中的标识符匹配
        self._verify_csr_identifiers(csr, order.identifiers)

        # 提取 Agent ID 列表
        agent_ids = [
            identifier["value"]
            for identifier in order.identifiers
            if identifier["type"] == "agent"
        ]

        if not agent_ids:
            raise AcmeException(
                status_code=400,
                error_name=AcmeError.INVALID_CERTIFICATE_FORMAT,
                error_msg="No valid agent identifiers found in order",
            )

        # 根据业务规则：每个Agent分别签发一张证书
        certificates = []
        for i, agent_id in enumerate(agent_ids):
            # 获取对应的Agent信息
            agent_info = None
            if agent_infos and i < len(agent_infos):
                # 查找匹配的Agent信息
                for info in agent_infos:
                    if hasattr(info, "agent_id") and info.agent_id == agent_id:
                        agent_info = info
                        break
                # 如果没找到匹配的，使用第一个作为默认
                if agent_info is None and agent_infos:
                    agent_info = agent_infos[0]

            # 为单个Agent生成证书
            cert_pem = self._generate_certificate_for_agent(csr, agent_id, agent_info)

            # 从生成的证书中提取序列号，确保数据库记录与实际证书一致
            serial_number = self._extract_serial_number_from_cert_pem(cert_pem)

            # 创建证书记录
            cert_data = CertificateCreate(
                order_id=order.id,
                serial_number=serial_number,
                certificate_pem=cert_pem,
                subject=self._extract_subject_from_cert_pem(cert_pem),
                not_before=beijing_now(),
                not_after=beijing_now()
                + timedelta(days=49),  # 49天有效期，符合文档要求
                aic=agent_id,  # 设置AIC字段
            )

            certificate = self._create_certificate(cert_data)
            certificates.append(certificate)

        return certificates

    def get_certificate_by_id(self, cert_id: str) -> Optional[AcmeCertificate]:
        """根据证书ID获取证书"""
        statement = select(AcmeCertificate).where(AcmeCertificate.cert_id == cert_id)
        return self.session.exec(statement).first()

    def revoke_certificate(
        self, certificate: AcmeCertificate, reason: Optional[int] = None
    ):
        """吊销证书"""
        certificate.status = CertificateStatus.REVOKED
        certificate.revoked_at = beijing_now()
        certificate.revocation_reason = (
            RevocationReason.from_acme_code(reason) if reason is not None else None
        )
        certificate.updated_at = beijing_now()

        self.session.add(certificate)
        self.session.commit()

    def _verify_csr_identifiers(
        self, csr: x509.CertificateSigningRequest, identifiers: List[Dict[str, str]]
    ):
        """验证 CSR 中的标识符"""
        # 提取 CSR 的主体名称
        subject = csr.subject
        cn = None
        for attribute in subject:
            if attribute.oid == NameOID.COMMON_NAME:
                cn = attribute.value
                break

        if not cn:
            raise AcmeException(
                status_code=400,
                error_name=AcmeError.INVALID_CERTIFICATE_FORMAT,
                error_msg="CSR must contain Common Name",
            )

        # 验证 CN 是否匹配订单中的标识符
        agent_ids = [
            identifier["value"]
            for identifier in identifiers
            if identifier["type"] == "agent"
        ]

        valid_cns = set(agent_ids)
        suffix = self.settings.agent_cn_domain_suffix_normalized
        if suffix:
            valid_cns.update(
                self.settings.build_agent_common_name(agent_id)
                for agent_id in agent_ids
            )

        if cn not in valid_cns:
            raise AcmeException(
                status_code=400,
                error_name=AcmeError.INVALID_CERTIFICATE_FORMAT,
                error_msg=f"CSR Common Name '{cn}' does not match any ordered identifiers",
            )

    def _generate_certificate(
        self,
        csr: x509.CertificateSigningRequest,
        identifiers: List[Dict[str, str]],
        agent_infos: Optional[List["AgentInfo"]] = None,
    ) -> str:
        """生成证书

        Args:
            csr: 证书签名请求
            identifiers: 标识符列表
            agent_infos: Agent信息列表，用于构造证书DN
        """
        # 提取 Agent ID 列表
        agent_ids = [
            identifier["value"]
            for identifier in identifiers
            if identifier["type"] == "agent"
        ]

        if not agent_ids:
            raise AcmeException(
                status_code=400,
                error_name=AcmeError.INVALID_CERTIFICATE_FORMAT,
                error_msg="No valid agent identifiers found in order",
            )

        # 构造证书DN信息
        cert_subject_components = {}
        if agent_infos and len(agent_infos) > 0:
            # 使用第一个Agent的信息作为主要信息
            primary_agent = agent_infos[0]
            cert_subject_components = primary_agent.get_certificate_subject_components()

        # 使用 CA 管理器签发证书
        ca_manager = get_ca_manager()
        try:
            cert_pem = ca_manager.sign_certificate(
                csr,
                agent_ids,
                validity_days=49,  # 符合文档要求的49天
                subject_components=cert_subject_components,
            )
            return cert_pem
        except Exception as e:
            raise AcmeException(
                status_code=500,
                error_name=AcmeError.SERVER_INTERNAL,
                error_msg=f"Certificate signing failed: {str(e)}",
            )

    def _generate_certificate_for_agent(
        self,
        csr: x509.CertificateSigningRequest,
        agent_id: str,
        agent_info: Optional["AgentInfo"] = None,
    ) -> str:
        """为单个Agent生成证书

        Args:
            csr: 证书签名请求
            agent_id: Agent ID
            agent_info: Agent信息，用于构造证书DN

        Returns:
            str: PEM格式的证书
        """
        # 构造证书DN信息
        cert_subject_components = {}
        if agent_info:
            cert_subject_components = agent_info.get_certificate_subject_components()

        # 使用 CA 管理器签发证书（单个Agent）
        ca_manager = get_ca_manager()
        try:
            cert_pem = ca_manager.sign_certificate(
                csr,
                [agent_id],  # 单个Agent的列表
                validity_days=49,  # 符合文档要求的49天
                subject_components=cert_subject_components,
            )
            return cert_pem
        except Exception as e:
            raise AcmeException(
                status_code=500,
                error_name=AcmeError.SERVER_INTERNAL,
                error_msg=f"Certificate signing failed for agent {agent_id}: {str(e)}",
            )

    def _extract_serial_number_from_cert_pem(self, cert_pem: str) -> str:
        """从PEM格式证书中提取序列号

        Args:
            cert_pem: PEM格式的证书字符串

        Returns:
            str: 16进制格式的序列号
        """
        try:
            cert = x509.load_pem_x509_certificate(cert_pem.encode(), default_backend())
            return format(cert.serial_number, "x").upper()
        except Exception as e:
            raise AcmeException(
                status_code=500,
                error_name=AcmeError.SERVER_INTERNAL,
                error_msg=f"Failed to extract serial number from certificate: {str(e)}",
            )

    def _extract_subject_from_csr(
        self, csr: x509.CertificateSigningRequest
    ) -> Dict[str, Any]:
        """从 CSR 提取主体信息"""
        subject_dict = {}
        for attribute in csr.subject:
            if attribute.oid == NameOID.COMMON_NAME:
                subject_dict["CN"] = attribute.value
            elif attribute.oid == NameOID.ORGANIZATION_NAME:
                subject_dict["O"] = attribute.value
            elif attribute.oid == NameOID.ORGANIZATIONAL_UNIT_NAME:
                subject_dict["OU"] = attribute.value
            elif attribute.oid == NameOID.COUNTRY_NAME:
                subject_dict["C"] = attribute.value

        return subject_dict

    def _extract_subject_from_cert_pem(self, cert_pem: str) -> Dict[str, Any]:
        """从证书PEM中提取主体信息

        Args:
            cert_pem: PEM格式的证书

        Returns:
            Dict[str, Any]: 主体信息字典
        """
        try:
            # 解析证书
            cert = x509.load_pem_x509_certificate(cert_pem.encode(), default_backend())

            # 提取主体信息
            subject_dict = {}
            for attribute in cert.subject:
                if attribute.oid == NameOID.COMMON_NAME:
                    subject_dict["CN"] = attribute.value
                elif attribute.oid == NameOID.ORGANIZATION_NAME:
                    subject_dict["O"] = attribute.value
                elif attribute.oid == NameOID.ORGANIZATIONAL_UNIT_NAME:
                    subject_dict["OU"] = attribute.value
                elif attribute.oid == NameOID.COUNTRY_NAME:
                    subject_dict["C"] = attribute.value
                elif attribute.oid == NameOID.STATE_OR_PROVINCE_NAME:
                    subject_dict["ST"] = attribute.value
                elif attribute.oid == NameOID.LOCALITY_NAME:
                    subject_dict["L"] = attribute.value

            return subject_dict
        except Exception as e:
            raise AcmeException(
                status_code=500,
                error_name=AcmeError.SERVER_INTERNAL,
                error_msg=f"Failed to extract subject from certificate: {str(e)}",
            )

    def _generate_serial_number(self) -> str:
        """生成证书序列号"""
        return secrets.token_hex(16)

    def _create_certificate(self, cert_data: CertificateCreate) -> AcmeCertificate:
        """创建证书记录"""
        cert_id = f"cert_{secrets.token_urlsafe(16)}"

        # 创建ACME证书记录
        certificate = AcmeCertificate(
            cert_id=cert_id,
            order_id=cert_data.order_id,
            serial_number=cert_data.serial_number,
            certificate_pem=cert_data.certificate_pem,
            subject=cert_data.subject,
            not_before=cert_data.not_before,
            not_after=cert_data.not_after,
            aic=cert_data.aic,  # 设置AIC字段
        )

        self.session.add(certificate)

        # 同时在Certificate表中创建记录，用于证书管理和批量吊销
        if cert_data.aic:
            from app.common.certificate_version import get_next_certificate_version
            
            common_cert = Certificate(
                certificate_type=CertificateType.AGENT,  # Agent证书类型
                serial_number=cert_data.serial_number,
                subject=f"CN={self.settings.build_agent_common_name(cert_data.aic)}",
                issuer="Agent Trusted Registration CA",  # 可以根据实际情况调整
                status=CertificateStatus.VALID,
                certificate_pem=cert_data.certificate_pem,
                public_key=self._extract_public_key_from_cert_pem(
                    cert_data.certificate_pem
                ),
                expires_at=cert_data.not_after,
                aic=cert_data.aic,  # 设置AIC字段用于批量查询
                version=get_next_certificate_version(self.session, cert_data.aic),
            )
            self.session.add(common_cert)

        self.session.commit()
        self.session.refresh(certificate)

        return certificate

    def _extract_public_key_from_cert_pem(self, cert_pem: str) -> str:
        """从证书PEM中提取公钥"""
        try:
            from cryptography.hazmat.primitives import serialization

            cert = x509.load_pem_x509_certificate(cert_pem.encode())
            public_key = cert.public_key()

            public_key_pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("utf-8")

            return public_key_pem
        except Exception as e:
            print(f"Failed to extract public key: {e}")
            return ""  # 返回空字符串作为fallback


# ================== 工厂函数 ==================


def get_nonce_service(session: Session = None) -> NonceService:
    """获取 Nonce 服务实例"""
    if session is None:
        session = next(get_session())
    return NonceService(session)


def get_account_service(session: Session = None) -> AccountService:
    """获取账户服务实例"""
    if session is None:
        session = next(get_session())
    return AccountService(session)


def get_order_service(session: Session = None) -> OrderService:
    """获取订单服务实例"""
    if session is None:
        session = next(get_session())
    return OrderService(session)


def get_authorization_service(session: Session = None) -> AuthorizationService:
    """获取授权服务实例"""
    if session is None:
        session = next(get_session())
    return AuthorizationService(session)


def get_challenge_service(session: Session = None) -> ChallengeService:
    """获取挑战服务实例"""
    if session is None:
        session = next(get_session())
    return ChallengeService(session)


# ValidationService已被移除，使用http01_validator中的服务


def get_certificate_service(session: Session = None) -> CertificateService:
    """获取证书服务实例"""
    if session is None:
        session = next(get_session())
    return CertificateService(session)
