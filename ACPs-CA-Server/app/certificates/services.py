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
                print(f"Failed to revoke certificate {cert.id}: {e} - services.py:252")
                continue

        return revoked_count
    
    def retrieve_certificate_by_aic_and_version(
        self, aic: str, version: Optional[int]
    ) -> Certificate:
        """
        根据 AIC 和版本号检索证书

        Args:
            aic: Agent Identity Code
            version: 版本号，如果为 None 则检索最新有效证书

        Returns:
            str: 证书内容（PEM 格式）

        Raises:
            ValueError: 如果未找到符合条件的证书
        """
        from sqlmodel import select
        from app.common import Certificate, CertificateStatus

        statement = select(Certificate).where(
            Certificate.aic == aic,
        )

        if version:
            statement = statement.where(Certificate.version == version)
        else:
            statement = statement.where(Certificate.status == CertificateStatus.VALID)

        statement = statement.order_by(Certificate.created_at.desc())

        certificate = self.db.exec(statement).first()

        if not certificate:
            raise ValueError("Certificate not found for the given AIC and version")

        return certificate
    
    def retrieve_certificate_by_cert(self, cert_pem: str)  -> Certificate:
        """
        从证书PEM中提取AIC

        Args:
            cert_pem: 证书PEM格式字符串

        Returns:
            Certificate: 证书对象
        """
        from sqlmodel import select
        from app.common import Certificate, CertificateStatus
        from sqlalchemy import func
        from urllib.parse import unquote
        
        try:
            # cert_pem 可能来自 URL query（出现 %0A、%20 等），先做一次 URL 解码。
            # 注意：不要用 unquote_plus，避免把 PEM/base64 里的 '+' 误当空格。
            cert_pem = unquote(cert_pem or "")

            # 1) 快路径：精确匹配（最快）
            statement = select(Certificate).where(Certificate.certificate_pem == cert_pem)
            certificate = self.db.exec(statement).first()
            if certificate:
                return certificate

            # 2) 兼容：入参可能把换行替换成空格/混用 \r\n，忽略所有空白后再匹配。
            normalized_input = "".join(cert_pem.split())
            statement = select(Certificate).where(
                func.regexp_replace(
                    Certificate.certificate_pem,
                    r"\\s+",
                    "",
                    "g",
                )
                == normalized_input
            )
            certificate = self.db.exec(statement).first()
            if certificate:
                return certificate

            # 3) 回退：在不支持 regexp_replace 的数据库上（例如 SQLite），用 Python 做归一化匹配。
            # 数据量很大时不建议使用该路径。
            candidates = self.db.exec(select(Certificate)).all()
            for item in candidates:
                if "".join((item.certificate_pem or "").split()) == normalized_input:
                    return item

            raise ValueError("Certificate not found for the given cert_pem")
        except Exception as e:
            print(f"Error retrieving certificate by cert: {e} - services.py:344")
            raise ValueError(f"Error retrieving certificate by cert: {e}")

