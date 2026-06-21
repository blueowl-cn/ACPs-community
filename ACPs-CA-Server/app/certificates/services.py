"""
证书管理服务层
"""

from typing import Optional, List
from uuid import UUID

from sqlmodel import Session

from app.common import (
    CertificateService,
    Certificate,
    CertificateType,
    CertificateStatus,
)


class CertificateManagementService(CertificateService):
    """证书管理扩展服务"""

    def __init__(self, db: Session):
        super().__init__(db)

    def create_root_certificate(
        self, subject_name: str, validity_days: int = 3650
    ) -> Certificate:
        """
        创建根证书

        Args:
            subject_name: 证书主体名称
            validity_days: 有效期天数，默认10年

        Returns:
            Certificate: 创建的根证书
        """
        cert_pem, private_key_pem = self.generate_certificate_pair(
            subject_name=subject_name,
            certificate_type=CertificateType.ROOT,
            validity_days=validity_days,
        )

        certificate_data = {
            "certificate_type": CertificateType.ROOT,
            "subject": subject_name,
            "issuer": subject_name,  # 根证书是自签名的
            "status": CertificateStatus.VALID,
            "certificate_pem": cert_pem,
            "public_key": self._extract_public_key_from_cert(cert_pem),
            "expires_at": self._calculate_expiry_date(validity_days),
        }

        return self.create_certificate(certificate_data)

    def create_intermediate_certificate(
        self, subject_name: str, parent_certificate_id: UUID, validity_days: int = 1825
    ) -> Optional[Certificate]:
        """
        创建中间证书

        Args:
            subject_name: 证书主体名称
            parent_certificate_id: 父证书ID
            validity_days: 有效期天数，默认5年

        Returns:
            Optional[Certificate]: 创建的中间证书或None
        """
        parent_certificate = self.get_certificate_by_id(parent_certificate_id)
        if (
            not parent_certificate
            or parent_certificate.status != CertificateStatus.VALID
        ):
            return None

        cert_pem, private_key_pem = self.generate_certificate_pair(
            subject_name=subject_name,
            certificate_type=CertificateType.INTERMEDIATE,
            validity_days=validity_days,
            parent_certificate=parent_certificate,
        )

        certificate_data = {
            "certificate_type": CertificateType.INTERMEDIATE,
            "subject": subject_name,
            "issuer": parent_certificate.subject,
            "status": CertificateStatus.VALID,
            "certificate_pem": cert_pem,
            "public_key": self._extract_public_key_from_cert(cert_pem),
            "parent_certificate_id": parent_certificate_id,
            "expires_at": self._calculate_expiry_date(validity_days),
        }

        return self.create_certificate(certificate_data)

    def renew_certificate(
        self, certificate_id: UUID, validity_days: Optional[int] = None
    ) -> Optional[Certificate]:
        """
        续期证书

        Args:
            certificate_id: 证书ID
            validity_days: 新的有效期天数，如果不指定则使用默认值

        Returns:
            Optional[Certificate]: 新的证书或None
        """
        old_certificate = self.get_certificate_by_id(certificate_id)
        if not old_certificate:
            return None

        # 确定续期天数
        if validity_days is None:
            if old_certificate.certificate_type == CertificateType.ROOT:
                validity_days = 3650  # 10年
            elif old_certificate.certificate_type == CertificateType.INTERMEDIATE:
                validity_days = 1825  # 5年
            else:
                validity_days = 365  # 1年

        # 生成新证书
        cert_pem, private_key_pem = self.generate_certificate_pair(
            subject_name=old_certificate.subject,
            certificate_type=old_certificate.certificate_type,
            validity_days=validity_days,
            parent_certificate=(
                self.get_certificate_by_id(old_certificate.parent_certificate_id)
                if old_certificate.parent_certificate_id
                else None
            ),
            aic=old_certificate.aic,
        )

        # 创建新证书
        certificate_data = {
            "certificate_type": old_certificate.certificate_type,
            "subject": old_certificate.subject,
            "issuer": old_certificate.issuer,
            "status": CertificateStatus.VALID,
            "certificate_pem": cert_pem,
            "public_key": self._extract_public_key_from_cert(cert_pem),
            "parent_certificate_id": old_certificate.parent_certificate_id,
            "aic": old_certificate.aic,
            "expires_at": self._calculate_expiry_date(validity_days),
        }

        new_certificate = self.create_certificate(certificate_data)

        # 吊销旧证书
        self.revoke_certificate(certificate_id, "续期替换")

        return new_certificate

    def get_certificate_chain(self, certificate_id: UUID) -> List[Certificate]:
        """
        获取证书链

        Args:
            certificate_id: 证书ID

        Returns:
            List[Certificate]: 证书链，从用户证书到根证书
        """
        chain = []
        current_cert = self.get_certificate_by_id(certificate_id)

        while current_cert:
            chain.append(current_cert)
            if current_cert.parent_certificate_id:
                current_cert = self.get_certificate_by_id(
                    current_cert.parent_certificate_id
                )
            else:
                break

        return chain

    def _extract_public_key_from_cert(self, cert_pem: str) -> str:
        """
        从证书PEM中提取公钥

        Args:
            cert_pem: 证书PEM格式字符串

        Returns:
            str: 公钥PEM格式字符串
        """
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization

        cert = x509.load_pem_x509_certificate(cert_pem.encode())
        public_key = cert.public_key()

        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

        return public_key_pem

    def _calculate_expiry_date(self, validity_days: int):
        """
        计算过期日期

        Args:
            validity_days: 有效期天数

        Returns:
            datetime: 过期日期
        """
        from datetime import timedelta
        from app.common import beijing_now

        return beijing_now() + timedelta(days=validity_days)

    def revoke_certificates_by_aic(self, aic: str, reason: str) -> int:
        """
        根据 AIC 批量吊销证书

        根据 ATR-DESIGN 规范，查找指定 AIC 的所有状态为 "pending" 或 "valid" 的证书并吊销。

        Args:
            aic: Agent Identity Code
            reason: 吊销原因

        Returns:
            int: 成功吊销的证书数量
        """
        from sqlmodel import select
        from app.common import Certificate, CertificateStatus

        # 查找所有与该 AIC 相关的有效证书
        # 直接使用 aic 字段进行查询
        statement = select(Certificate).where(
            Certificate.aic == aic,
            Certificate.status.in_(
                [CertificateStatus.PENDING, CertificateStatus.VALID]
            ),
        )

        certificates = self.db.exec(statement).all()

        revoked_count = 0
        for cert in certificates:
            try:
                # 调用父类的吊销方法
                if self.revoke_certificate(cert.id, reason):
                    revoked_count += 1
            except Exception as e:
                # 记录错误但继续处理其他证书
                print(f"Failed to revoke certificate {cert.id}: {e}")
                continue

        return revoked_count
