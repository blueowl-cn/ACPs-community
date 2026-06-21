"""
CRL (Certificate Revocation List) 测试

测试CRL的创建、更新、查询和下载功能
"""

import pytest
from sqlmodel import Session
from datetime import timedelta
from uuid import uuid4
import time

from app.core.db_session import engine
from app.common import (
    Certificate,
    CRLStatus,
    CertificateStatus,
    RevocationReason,
    beijing_now,
)
from app.common import CRLService


pytestmark = pytest.mark.crl


@pytest.fixture
def db_session():
    """数据库会话fixture"""
    with Session(engine) as session:
        yield session


@pytest.fixture
def crl_service(db_session):
    """CRL服务fixture"""
    return CRLService(db_session)


@pytest.fixture
def sample_certificate(db_session):
    """创建示例证书"""
    # 生成符合标准的16进制序列号
    serial_hex = f"{1001:04X}{uuid4().hex[:12].upper()}"

    cert = Certificate(
        certificate_type="user",
        serial_number=serial_hex,
        subject="CN=test.example.com,O=Test Org,C=CN",
        issuer="CN=Test CA,O=Test CA,C=CN",
        status=CertificateStatus.VALID,
        issued_at=beijing_now(),
        expires_at=beijing_now() + timedelta(days=365),
        certificate_pem="-----BEGIN CERTIFICATE-----\nTEST_CERT\n-----END CERTIFICATE-----",
        public_key="TEST_PUBLIC_KEY",
    )
    db_session.add(cert)
    db_session.commit()
    db_session.refresh(cert)
    return cert


@pytest.fixture
def revoked_certificate(db_session):
    """创建已吊销证书"""
    # 生成符合标准的16进制序列号
    serial_hex = f"{9999:04X}{uuid4().hex[:12].upper()}"

    cert = Certificate(
        certificate_type="user",
        serial_number=serial_hex,
        subject="CN=revoked.example.com,O=Test Org,C=CN",
        issuer="CN=Test CA,O=Test CA,C=CN",
        status=CertificateStatus.REVOKED,
        issued_at=beijing_now() - timedelta(days=30),
        expires_at=beijing_now() + timedelta(days=335),
        revoked_at=beijing_now() - timedelta(days=1),
        revocation_reason=RevocationReason.KEY_COMPROMISE,
        certificate_pem="-----BEGIN CERTIFICATE-----\nREVOKED_CERT\n-----END CERTIFICATE-----",
        public_key="REVOKED_PUBLIC_KEY",
    )
    db_session.add(cert)
    db_session.commit()
    db_session.refresh(cert)
    return cert


class TestCRLGeneration:
    """测试CRL生成功能"""

    def test_generate_new_crl_empty(self, crl_service, clean_db):
        """测试生成空CRL（无吊销证书）"""
        crl = crl_service.generate_new_crl(
            issuer="CN=Test CA,O=Test CA,C=CN", next_update_hours=24
        )

        assert crl is not None
        assert crl.status == CRLStatus.CURRENT
        assert crl.revoked_certificates_count == 0
        assert crl.crl_pem.startswith("-----BEGIN X509 CRL-----")
        assert crl.crl_pem.strip().endswith("-----END X509 CRL-----")

    def test_generate_new_crl_with_revoked_cert(
        self, crl_service, revoked_certificate, clean_db
    ):
        """测试生成包含吊销证书的CRL"""
        crl = crl_service.generate_new_crl(
            issuer="CN=Test CA,O=Test CA,C=CN", next_update_hours=24
        )

        assert crl is not None
        assert crl.status == CRLStatus.CURRENT
        assert crl.revoked_certificates_count == 1
        assert crl.crl_pem.startswith("-----BEGIN X509 CRL-----")

    def test_crl_version_format(self, crl_service, clean_db):
        """测试CRL版本号格式"""
        crl = crl_service.generate_new_crl(issuer="CN=Test CA")

        # 版本号应该是YYYYMMDDHHMMSS + 毫秒格式
        assert len(crl.version) == 17
        assert crl.version.isdigit()

        # 检查年份部分（前4位）
        current_year = beijing_now().year
        version_year = int(crl.version[:4])
        assert version_year == current_year

    def test_crl_number_increment(self, crl_service, clean_db):
        """测试CRL编号递增"""
        # 添加微小延迟确保版本号不同
        crl1 = crl_service.generate_new_crl(issuer="CN=Test CA")
        time.sleep(0.01)  # 10毫秒延迟
        crl2 = crl_service.generate_new_crl(issuer="CN=Test CA")

        assert crl2.crl_number == crl1.crl_number + 1
        assert crl1.version != crl2.version

    def test_old_crl_superseded(self, crl_service, clean_db):
        """测试旧CRL被正确标记为已取代"""
        # 生成第一个CRL
        crl1 = crl_service.generate_new_crl(issuer="CN=Test CA")
        assert crl1.status == CRLStatus.CURRENT

        # 添加延迟确保版本号不同
        time.sleep(0.01)
        # 生成第二个CRL
        crl2 = crl_service.generate_new_crl(issuer="CN=Test CA")
        assert crl2.status == CRLStatus.CURRENT

        # 刷新第一个CRL的状态
        crl_service.db.refresh(crl1)
        assert crl1.status == CRLStatus.SUPERSEDED


class TestCRLQuery:
    """测试CRL查询功能"""

    def test_get_current_crl(self, crl_service, clean_db):
        """测试获取当前CRL"""
        # 生成一个CRL
        created_crl = crl_service.generate_new_crl(issuer="CN=Test CA")

        # 查询当前CRL
        current_crl = crl_service.get_current_crl()

        assert current_crl is not None
        assert current_crl.id == created_crl.id
        assert current_crl.status == CRLStatus.CURRENT

    def test_get_crl_by_number(self, crl_service, clean_db):
        """测试根据编号获取CRL"""
        # 生成一个CRL
        created_crl = crl_service.generate_new_crl(issuer="CN=Test CA")

        # 根据编号查询
        found_crl = crl_service.get_crl_by_number(created_crl.crl_number)

        assert found_crl is not None
        assert found_crl.id == created_crl.id
        assert found_crl.crl_number == created_crl.crl_number


def test_simple():
    """简单测试"""
    assert True
