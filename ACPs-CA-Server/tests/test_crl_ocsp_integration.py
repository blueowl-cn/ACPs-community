"""
CRL和OCSP集成测试

测试CRL和OCSP功能的端到端集成，包括证书吊销、CRL更新、OCSP状态同步等
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from datetime import datetime, timedelta
from uuid import uuid4

from app.core.db_session import engine
from app.common import (
    Certificate,
    OCSPResponder,
    CertificateStatus,
    RevocationReason,
)
from app.common import CRLService, OCSPService


pytestmark = [pytest.mark.crl_ocsp, pytest.mark.integration]


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
def ocsp_service(db_session):
    """OCSP服务fixture"""
    return OCSPService(db_session)


@pytest.fixture
def test_certificates(db_session):
    """创建测试用的证书集合"""
    certificates = []

    # 创建3个有效证书
    for i in range(3):
        cert = Certificate(
            certificate_type="user",
            serial_number=f"VALID{i:03d}{uuid4().hex[:8].upper()}",
            subject=f"CN=test{i}.example.com,O=Test Org,C=CN",
            issuer="CN=Test CA,O=Test CA,C=CN",
            status=CertificateStatus.VALID,
            issued_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=365),
            certificate_pem=f"-----BEGIN CERTIFICATE-----\nTEST_CERT_{i}\n-----END CERTIFICATE-----",
            public_key=f"TEST_PUBLIC_KEY_{i}",
        )
        db_session.add(cert)
        certificates.append(cert)

    # 创建1个已吊销证书
    revoked_cert = Certificate(
        certificate_type="user",
        serial_number=f"REVOKED{uuid4().hex[:8].upper()}",
        subject="CN=revoked.example.com,O=Test Org,C=CN",
        issuer="CN=Test CA,O=Test CA,C=CN",
        status=CertificateStatus.REVOKED,
        issued_at=datetime.utcnow() - timedelta(days=30),
        expires_at=datetime.utcnow() + timedelta(days=335),
        revoked_at=datetime.utcnow() - timedelta(days=1),
        revocation_reason=RevocationReason.KEY_COMPROMISE,
        certificate_pem="-----BEGIN CERTIFICATE-----\nREVOKED_CERT\n-----END CERTIFICATE-----",
        public_key="REVOKED_PUBLIC_KEY",
    )
    db_session.add(revoked_cert)
    certificates.append(revoked_cert)

    # 创建1个过期证书
    expired_cert = Certificate(
        certificate_type="user",
        serial_number=f"EXPIRED{uuid4().hex[:8].upper()}",
        subject="CN=expired.example.com,O=Test Org,C=CN",
        issuer="CN=Test CA,O=Test CA,C=CN",
        status=CertificateStatus.EXPIRED,
        issued_at=datetime.utcnow() - timedelta(days=400),
        expires_at=datetime.utcnow() - timedelta(days=35),
        certificate_pem="-----BEGIN CERTIFICATE-----\nEXPIRED_CERT\n-----END CERTIFICATE-----",
        public_key="EXPIRED_PUBLIC_KEY",
    )
    db_session.add(expired_cert)
    certificates.append(expired_cert)

    db_session.commit()
    for cert in certificates:
        db_session.refresh(cert)

    return certificates


@pytest.fixture
def ocsp_responder(db_session):
    """创建OCSP响应器"""
    responder = OCSPResponder(
        name="Test OCSP Responder",
        certificate_pem="-----BEGIN CERTIFICATE-----\nOCSP_RESPONDER_CERT\n-----END CERTIFICATE-----",
        private_key_pem="-----BEGIN PRIVATE KEY-----\nOCSP_RESPONDER_KEY\n-----END PRIVATE KEY-----",
        certificate_serial="OCSP123456789",
        endpoints=["http://ocsp.test.com"],
        supported_extensions=["basic", "nonce"],
        is_active=True,
    )
    db_session.add(responder)
    db_session.commit()
    db_session.refresh(responder)
    return responder


class TestCRLOCSPBasicIntegration:
    """测试CRL和OCSP基本集成功能"""

    def test_initial_state_consistency(
        self, client: TestClient, test_certificates, ocsp_responder
    ):
        """测试初始状态下CRL和OCSP的一致性"""
        # 生成初始CRL
        crl_response = client.post("/acps-atr-v1/crl/refresh")
        assert crl_response.status_code == 200

        # 获取CRL详情
        crl_detail_response = client.get("/acps-atr-v1/crl/detail")
        assert crl_detail_response.status_code == 200
        crl_data = crl_detail_response.json()

        # 获取所有吊销证书的序列号
        crl_revoked_serials = set(
            cert["serialNumber"] for cert in crl_data["revokedCertificates"]
        )

        # 测试OCSP状态与CRL一致性
        for cert in test_certificates:
            ocsp_response = client.get(f"/acps-atr-v1/ocsp/certificate/{cert.serial_number}")
            assert ocsp_response.status_code == 200
            ocsp_data = ocsp_response.json()

            if cert.status == CertificateStatus.REVOKED:
                # 吊销证书应该在CRL中
                assert cert.serial_number in crl_revoked_serials
                # OCSP也应该返回revoked状态
                assert ocsp_data["certificateStatus"] == "revoked"
            elif cert.status == CertificateStatus.VALID:
                # 有效证书不应该在CRL中
                assert cert.serial_number not in crl_revoked_serials
                # OCSP应该返回good状态
                assert ocsp_data["certificateStatus"] == "good"
            elif cert.status == CertificateStatus.EXPIRED:
                # 过期证书可能在CRL中，也可能不在（取决于实现）
                # OCSP应该返回expired状态
                assert ocsp_data["certificateStatus"] == "expired"

    def test_certificate_lifecycle_integration(
        self, client: TestClient, test_certificates
    ):
        """测试证书生命周期的完整集成"""
        # 找到一个有效证书用于测试
        valid_cert = None
        for cert in test_certificates:
            if cert.status == CertificateStatus.VALID:
                valid_cert = cert
                break

        assert valid_cert is not None, "需要至少一个有效证书进行测试"

        # 1. 初始状态：证书有效
        ocsp_response = client.get(
            f"/acps-atr-v1/ocsp/certificate/{valid_cert.serial_number}"
        )
        assert ocsp_response.status_code == 200
        assert ocsp_response.json()["certificateStatus"] == "good"

        # 2. 吊销证书
        revoke_response = client.post(
            f"/admin/certificates/{valid_cert.id}/revoke",
            params={"reason": "keyCompromise"},
        )
        assert revoke_response.status_code == 200

        # 3. 立即检查OCSP状态（应该已更新）
        ocsp_response = client.get(
            f"/acps-atr-v1/ocsp/certificate/{valid_cert.serial_number}"
        )
        assert ocsp_response.status_code == 200
        ocsp_data = ocsp_response.json()
        assert ocsp_data["certificateStatus"] == "revoked"
        assert ocsp_data["revocationReason"] == "keyCompromise"

        # 4. 刷新CRL
        crl_refresh_response = client.post("/acps-atr-v1/crl/refresh")
        assert crl_refresh_response.status_code == 200

        # 5. 检查CRL是否包含新吊销的证书
        crl_detail_response = client.get("/acps-atr-v1/crl/detail")
        assert crl_detail_response.status_code == 200
        crl_data = crl_detail_response.json()

        revoked_serials = [
            cert["serialNumber"] for cert in crl_data["revokedCertificates"]
        ]
        assert valid_cert.serial_number in revoked_serials

        # 6. 验证CRL中的吊销原因
        for revoked_cert in crl_data["revokedCertificates"]:
            if revoked_cert["serialNumber"] == valid_cert.serial_number:
                assert revoked_cert["reason"] == "keyCompromise"
                break
        else:
            pytest.fail(f"Certificate {valid_cert.serial_number} not found in CRL")

    def test_batch_ocsp_consistency(self, client: TestClient, test_certificates):
        """测试批量OCSP查询的一致性"""
        # 准备批量查询请求
        certificate_requests = [
            {
                "serial_number": cert.serial_number,
                "issuer_key_hash": "d042ee4e30dcd77e3a2f8eb3f5d8fe8673567864",
            }
            for cert in test_certificates
        ]

        # 添加一个不存在的证书
        certificate_requests.append(
            {
                "serial_number": "NONEXISTENT123456",
                "issuer_key_hash": "d042ee4e30dcd77e3a2f8eb3f5d8fe8673567864",
            }
        )

        # 执行批量查询
        batch_response = client.post(
            "/acps-atr-v1/ocsp/batch", json={"certificates": certificate_requests}
        )
        assert batch_response.status_code == 200

        batch_data = batch_response.json()
        assert "responses" in batch_data
        assert len(batch_data["responses"]) == len(certificate_requests)

        # 验证批量查询结果与单独查询结果一致
        for cert in test_certificates:
            # 单独查询
            single_response = client.get(
                f"/acps-atr-v1/ocsp/certificate/{cert.serial_number}"
            )
            single_data = single_response.json()

            # 在批量结果中找到对应的响应
            batch_cert_response = None
            for resp in batch_data["responses"]:
                if resp["serial_number"] == cert.serial_number:
                    batch_cert_response = resp
                    break

            assert batch_cert_response is not None
            assert batch_cert_response["status"] == single_data["certificateStatus"]


class TestCRLOCSPErrorHandling:
    """测试CRL和OCSP错误处理"""

    def test_crl_generation_without_ca(self, client: TestClient):
        """测试在没有CA证书时的CRL生成"""
        # 这个测试依赖于CA管理器的配置
        # 如果CA证书不存在，应该返回适当的错误
        response = client.post("/acps-atr-v1/crl/refresh")
        # 根据实际实现，这里可能返回200（如果有默认CA）或500（如果没有CA）
        assert response.status_code in [200, 500]

    def test_ocsp_response_without_responder(self, client: TestClient, db_session):
        """测试在没有OCSP响应器时的行为"""
        # 删除所有OCSP响应器
        for responder in db_session.exec(select(OCSPResponder)).all():
            db_session.delete(responder)
        db_session.commit()

        # 获取响应器信息应该返回404
        response = client.get("/acps-atr-v1/ocsp/responder/info")
        assert response.status_code == 404

        # 但是证书状态查询仍应该工作
        response = client.get("/acps-atr-v1/ocsp/certificate/TEST123")
        assert response.status_code == 200

    def test_invalid_certificate_id_revocation(self, client: TestClient):
        """测试使用无效证书ID进行吊销"""
        invalid_id = "00000000-0000-0000-0000-000000000000"

        response = client.post(
            f"/admin/certificates/{invalid_id}/revoke",
            params={"reason": "keyCompromise"},
        )
        assert response.status_code == 404

    def test_malformed_ocsp_requests(self, client: TestClient):
        """测试格式错误的OCSP请求"""
        # 测试格式错误的批量请求
        malformed_requests = [
            {},  # 空请求
            {"certificates": "not_a_list"},  # 错误的数据类型
            {"certificates": [{"wrong_field": "value"}]},  # 错误的字段名
        ]

        for request_data in malformed_requests:
            response = client.post("/acps-atr-v1/ocsp/batch", json=request_data)
            assert response.status_code in [400, 422]  # 应该返回客户端错误


class TestCRLOCSPPerformance:
    """测试CRL和OCSP性能"""

    def test_crl_generation_performance(self, client: TestClient, test_certificates):
        """测试CRL生成性能"""
        import time

        start_time = time.time()
        response = client.post("/acps-atr-v1/crl/refresh")
        end_time = time.time()

        assert response.status_code == 200

        # CRL生成应该在合理时间内完成（这里设置为5秒）
        generation_time = end_time - start_time
        assert (
            generation_time < 5.0
        ), f"CRL generation took {generation_time}s, which is too slow"

    def test_ocsp_response_performance(self, client: TestClient, test_certificates):
        """测试OCSP响应性能"""
        import time

        # 测试单个查询性能
        if test_certificates:
            cert = test_certificates[0]
            start_time = time.time()
            response = client.get(f"/acps-atr-v1/ocsp/certificate/{cert.serial_number}")
            end_time = time.time()

            assert response.status_code == 200

            # 单个OCSP查询应该很快（这里设置为1秒）
            response_time = end_time - start_time
            assert (
                response_time < 1.0
            ), f"OCSP response took {response_time}s, which is too slow"

    def test_batch_ocsp_performance(self, client: TestClient, test_certificates):
        """测试批量OCSP查询性能"""
        import time

        # 创建包含所有测试证书的批量请求
        certificate_requests = [
            {
                "serial_number": cert.serial_number,
                "issuer_key_hash": "d042ee4e30dcd77e3a2f8eb3f5d8fe8673567864",
            }
            for cert in test_certificates
        ]

        start_time = time.time()
        response = client.post(
            "/acps-atr-v1/ocsp/batch", json={"certificates": certificate_requests}
        )
        end_time = time.time()

        assert response.status_code == 200

        # 批量查询应该比单独查询更高效
        batch_time = end_time - start_time
        assert batch_time < 2.0, f"Batch OCSP took {batch_time}s, which is too slow"


class TestCRLOCSPDataConsistency:
    """测试CRL和OCSP数据一致性"""

    def test_multiple_revocations_consistency(
        self, client: TestClient, test_certificates
    ):
        """测试多次吊销操作的数据一致性"""
        valid_certs = [
            cert for cert in test_certificates if cert.status == CertificateStatus.VALID
        ]

        if len(valid_certs) < 2:
            pytest.skip("需要至少2个有效证书进行此测试")

        # 记录初始状态 - 先刷新CRL以确保有当前CRL
        refresh_response = client.post("/acps-atr-v1/crl/refresh")
        assert refresh_response.status_code == 200

        initial_crl_response = client.get("/acps-atr-v1/crl/detail")
        assert initial_crl_response.status_code == 200
        initial_crl_data = initial_crl_response.json()
        initial_revoked_count = initial_crl_data["revokedCertificatesCount"]

        # 吊销多个证书
        revoked_serials = []
        for cert in valid_certs[:2]:  # 吊销前两个
            revoke_response = client.post(
                f"/admin/certificates/{cert.id}/revoke",
                params={"reason": "keyCompromise"},
            )
            assert revoke_response.status_code == 200
            revoked_serials.append(cert.serial_number)

        # 刷新CRL
        crl_refresh_response = client.post("/acps-atr-v1/crl/refresh")
        assert crl_refresh_response.status_code == 200

        # 验证CRL包含所有吊销的证书
        final_crl_response = client.get("/acps-atr-v1/crl/detail")
        final_crl_data = final_crl_response.json()

        assert final_crl_data["revokedCertificatesCount"] == initial_revoked_count + 2

        final_revoked_serials = [
            cert["serialNumber"] for cert in final_crl_data["revokedCertificates"]
        ]
        for serial in revoked_serials:
            assert serial in final_revoked_serials

        # 验证OCSP状态也已更新
        for serial in revoked_serials:
            ocsp_response = client.get(f"/acps-atr-v1/ocsp/certificate/{serial}")
            assert ocsp_response.status_code == 200
            assert ocsp_response.json()["certificateStatus"] == "revoked"

    def test_crl_version_progression(self, client: TestClient):
        """测试CRL版本的正确递进"""
        # 获取当前CRL版本
        crl_info_response = client.get("/acps-atr-v1/crl/info")
        if crl_info_response.status_code == 200:
            initial_version = crl_info_response.json()["version"]
        else:
            initial_version = None

        # 刷新CRL
        refresh_response = client.post("/acps-atr-v1/crl/refresh")
        assert refresh_response.status_code == 200
        new_version = refresh_response.json()["version"]

        # 新版本应该大于旧版本（按字符串比较应该也成立，因为使用时间戳格式）
        if initial_version:
            assert new_version > initial_version

        # 再次刷新
        refresh_response2 = client.post("/acps-atr-v1/crl/refresh")
        assert refresh_response2.status_code == 200
        newer_version = refresh_response2.json()["version"]

        assert newer_version > new_version

    def test_database_transaction_consistency(
        self, client: TestClient, test_certificates, db_session
    ):
        """测试数据库事务的一致性"""
        valid_cert = None
        for cert in test_certificates:
            if cert.status == CertificateStatus.VALID:
                valid_cert = cert
                break

        if not valid_cert:
            pytest.skip("需要至少一个有效证书进行此测试")

        # 记录吊销前的数据库状态
        initial_revoked_count = db_session.exec(
            select(Certificate).where(Certificate.status == CertificateStatus.REVOKED)
        ).all()
        initial_count = len(initial_revoked_count)

        # 吊销证书
        revoke_response = client.post(
            f"/admin/certificates/{valid_cert.id}/revoke",
            params={"reason": "keyCompromise"},
        )
        assert revoke_response.status_code == 200

        # 验证数据库状态已更新
        db_session.refresh(valid_cert)
        assert valid_cert.status == CertificateStatus.REVOKED
        assert valid_cert.revocation_reason == RevocationReason.KEY_COMPROMISE
        assert valid_cert.revoked_at is not None

        # 验证总数正确
        final_revoked_count = db_session.exec(
            select(Certificate).where(Certificate.status == CertificateStatus.REVOKED)
        ).all()
        assert len(final_revoked_count) == initial_count + 1
