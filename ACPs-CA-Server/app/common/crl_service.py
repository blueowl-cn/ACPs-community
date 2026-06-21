"""
CRL (Certificate Revocation List) 业务服务
"""

from datetime import timedelta
from typing import Optional, List, Tuple

from sqlmodel import Session, select, and_, desc, func
from cryptography import x509
from cryptography.x509 import ReasonFlags
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import (
    Encoding,
)

from .crl_model import CRL, CRLStatus, RevokedCertificateEntry
from .certificate_model import Certificate, CertificateStatus
from .time_utils import beijing_now
from ..core.ca_manager import get_ca_manager


class CRLService:
    """CRL管理服务"""

    def __init__(self, db: Session):
        self.db = db

    def expire_old_crls_except(self, exclude_id: str) -> None:
        """将旧的CRL标记为已过期（除了指定ID的CRL）"""
        try:
            # 将所有当前状态的CRL标记为已过期，除了新创建的CRL
            statement = select(CRL).where(
                and_(CRL.status == CRLStatus.CURRENT, CRL.id != exclude_id)
            )
            old_crls = self.db.exec(statement).all()

            for crl in old_crls:
                crl.status = CRLStatus.EXPIRED
                self.db.add(crl)

            self.db.commit()

        except Exception as e:
            self.db.rollback()
            raise e

    def expire_old_crls(self) -> None:
        """将旧的CRL标记为已过期"""
        try:
            # 将所有当前状态的CRL标记为已过期
            statement = select(CRL).where(CRL.status == CRLStatus.CURRENT)
            old_crls = self.db.exec(statement).all()

            for crl in old_crls:
                crl.status = CRLStatus.EXPIRED
                self.db.add(crl)

            self.db.commit()

        except Exception as e:
            self.db.rollback()
            raise e

    def get_current_crl(self) -> Optional[CRL]:
        """获取当前有效的CRL"""
        statement = (
            select(CRL)
            .where(CRL.status == CRLStatus.CURRENT)
            .order_by(desc(CRL.this_update))
            .limit(1)
        )
        return self.db.exec(statement).first()

    def get_crl_by_version(self, version: str) -> Optional[CRL]:
        """根据版本号获取CRL"""
        statement = select(CRL).where(CRL.version == version)
        return self.db.exec(statement).first()

    def get_crl_by_number(self, crl_number: int) -> Optional[CRL]:
        """根据CRL编号获取CRL"""
        statement = select(CRL).where(CRL.crl_number == crl_number)
        return self.db.exec(statement).first()

    def get_crl_list(
        self,
        status: Optional[CRLStatus] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[CRL], int]:
        """获取CRL列表"""
        statement = select(CRL)

        if status:
            statement = statement.where(CRL.status == status)

        # 获取总数
        total_statement = select(func.count(CRL.id))
        if status:
            total_statement = total_statement.where(CRL.status == status)
        total = self.db.exec(total_statement).one()

        # 分页查询
        statement = statement.order_by(desc(CRL.this_update))
        statement = statement.offset((page - 1) * page_size).limit(page_size)

        crls = self.db.exec(statement).all()
        return crls, total

    def generate_new_crl(
        self,
        issuer: str,
        next_update_hours: int = 24,
        distribution_points: Optional[List[str]] = None,
    ) -> CRL:
        """生成新的CRL"""
        # 获取CA管理器
        ca_manager = get_ca_manager()

        # 生成版本号（YYYYMMDDHHMMSS + 毫秒格式以确保唯一性）
        now = beijing_now()
        version = now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}"

        # 获取下一个CRL编号
        last_crl = self.db.exec(
            select(CRL).order_by(desc(CRL.crl_number)).limit(1)
        ).first()
        crl_number = (last_crl.crl_number + 1) if last_crl else 1

        # 获取所有吊销的证书
        revoked_certs = self.db.exec(
            select(Certificate).where(Certificate.status == CertificateStatus.REVOKED)
        ).all()

        # 构建吊销证书列表
        revoked_cert_list = []
        for cert in revoked_certs:
            if cert.revoked_at and cert.revocation_reason:
                # Convert serial number to integer
                # If it's already a hex string, parse as hex, otherwise use hash
                try:
                    # Try to parse as hex first
                    serial_int = int(cert.serial_number, 16)
                except ValueError:
                    # If not valid hex, create a hash from the string
                    import hashlib

                    serial_int = int(
                        hashlib.sha256(cert.serial_number.encode()).hexdigest()[:16], 16
                    )

                # 获取正确的ReasonFlags值
                reason_code = cert.revocation_reason.to_acme_code()
                reason_flag_mapping = {
                    0: ReasonFlags.unspecified,
                    1: ReasonFlags.key_compromise,
                    2: ReasonFlags.ca_compromise,
                    3: ReasonFlags.affiliation_changed,
                    4: ReasonFlags.superseded,
                    5: ReasonFlags.cessation_of_operation,
                }
                reason_flag = reason_flag_mapping.get(
                    reason_code, ReasonFlags.unspecified
                )

                revoked_cert_list.append(
                    x509.RevokedCertificateBuilder()
                    .serial_number(serial_int)
                    .revocation_date(cert.revoked_at)
                    .add_extension(
                        x509.CRLReason(reason_flag),
                        critical=False,
                    )
                    .build()
                )

        # 生成CRL
        next_update = now + timedelta(hours=next_update_hours)
        crl_builder = (
            x509.CertificateRevocationListBuilder()
            .issuer_name(ca_manager.ca_cert.subject)
            .last_update(now)
            .next_update(next_update)
        )

        # 添加吊销证书
        for revoked_cert in revoked_cert_list:
            crl_builder = crl_builder.add_revoked_certificate(revoked_cert)

        # 添加CRL编号扩展
        crl_builder = crl_builder.add_extension(
            x509.CRLNumber(crl_number), critical=False
        )

        # 签名CRL
        crl = crl_builder.sign(
            private_key=ca_manager.ca_private_key,
            algorithm=hashes.SHA256(),
        )

        # 转换为不同格式
        crl_der = crl.public_bytes(Encoding.DER)
        crl_pem = crl.public_bytes(Encoding.PEM).decode("utf-8")

        # 默认分发点
        if not distribution_points:
            distribution_points = ["https://ca.example.com/api/v1/crl/current"]

        # 获取签名密钥ID
        signature_key_id = ca_manager.ca_cert.extensions.get_extension_for_oid(
            x509.oid.ExtensionOID.SUBJECT_KEY_IDENTIFIER
        ).value.key_identifier.hex()

        # 创建CRL记录
        crl_record = CRL(
            version=version,
            crl_number=crl_number,
            issuer=issuer,
            this_update=now,
            next_update=next_update,
            status=CRLStatus.CURRENT,
            revoked_certificates_count=len(revoked_certs),
            crl_der=crl_der,
            crl_pem=crl_pem,
            crl_size=len(crl_der),
            distribution_points=distribution_points,
            signature_algorithm="SHA256withRSA",
            signature_key_id=signature_key_id,
        )

        # 将之前的CRL标记为已取代
        self.db.exec(
            select(CRL)
            .where(CRL.status == CRLStatus.CURRENT)
            .where(CRL.id != crl_record.id)
        )
        for old_crl in self.db.exec(
            select(CRL).where(CRL.status == CRLStatus.CURRENT)
        ).all():
            old_crl.status = CRLStatus.SUPERSEDED
            self.db.add(old_crl)

        # 保存新CRL
        self.db.add(crl_record)

        # 创建吊销证书条目
        for cert in revoked_certs:
            if cert.revoked_at and cert.revocation_reason:
                entry = RevokedCertificateEntry(
                    crl_id=crl_record.id,
                    serial_number=cert.serial_number,
                    revocation_date=cert.revoked_at,
                    revocation_reason=cert.revocation_reason,
                )
                self.db.add(entry)

        self.db.commit()
        self.db.refresh(crl_record)

        return crl_record

    def get_crl_distribution_points(self) -> dict:
        """获取CRL分发点配置"""
        current_crl = self.get_current_crl()
        if not current_crl:
            return {
                "primary": "https://ca.example.com/api/v1/crl/current",
                "mirrors": [],
                "update_interval": "PT24H",
                "max_age": "PT48H",
            }

        return {
            "primary": (
                current_crl.distribution_points[0]
                if current_crl.distribution_points
                else "https://ca.example.com/api/v1/crl/current"
            ),
            "mirrors": (
                current_crl.distribution_points[1:]
                if len(current_crl.distribution_points) > 1
                else []
            ),
            "update_interval": "PT24H",
            "max_age": "PT48H",
        }

    def is_crl_expired(self, crl: CRL) -> bool:
        """检查CRL是否过期"""
        return beijing_now() > crl.next_update

    def mark_expired_crls(self) -> int:
        """标记过期的CRL"""
        now = beijing_now()
        expired_crls = self.db.exec(
            select(CRL).where(
                and_(CRL.status == CRLStatus.CURRENT, CRL.next_update < now)
            )
        ).all()

        count = 0
        for crl in expired_crls:
            crl.status = CRLStatus.EXPIRED
            self.db.add(crl)
            count += 1

        if count > 0:
            self.db.commit()

        return count
