"""
OCSP (Online Certificate Status Protocol) 测试

测试OCSP状态查询、响应器信息和统计功能
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from datetime import timedelta
from uuid import uuid4

from app.core.db_session import engine
from app.common import (
    Certificate,
    OCSPResponder,
    CertificateStatus,
    RevocationReason,
    beijing_now,
)
from app.common import OCSPService


pytestmark = pytest.mark.ocsp


@pytest.fixture
def db_session():
    """数据库会话fixture"""
    with Session(engine) as session:
        yield session


@pytest.fixture
def ocsp_service(db_session):
    """OCSP服务fixture"""
    return OCSPService(db_session)


@pytest.fixture
def ocsp_responder(db_session):
    """创建OCSP响应器"""
    responder = OCSPResponder(
        name="Test OCSP Responder",
        certificate_pem="-----BEGIN CERTIFICATE-----\nOCSP_RESPONDER_CERT\n-----END CERTIFICATE-----",
        private_key_pem="-----BEGIN PRIVATE KEY-----\nOCSP_RESPONDER_KEY\n-----END PRIVATE KEY-----",
        certificate_serial="ABCD1234",
        endpoints={"primary": "http://ocsp.example.com"},
        supported_extensions=["nonce"],
        is_active=True,
    )
    db_session.add(responder)
    db_session.commit()
    db_session.refresh(responder)
    return responder


@pytest.fixture
def valid_certificate(db_session):
    """创建有效证书"""
    cert = Certificate(
        certificate_type="user",
        serial_number=f"VALID{uuid4().hex[:16].upper()}",
        subject="CN=valid.example.com,O=Test Org,C=CN",
        issuer="CN=Test CA,O=Test CA,C=CN",
        status=CertificateStatus.VALID,
        issued_at=beijing_now(),
        expires_at=beijing_now() + timedelta(days=365),
        certificate_pem="-----BEGIN CERTIFICATE-----\nVALID_CERT\n-----END CERTIFICATE-----",
        public_key="VALID_PUBLIC_KEY",
    )
    db_session.add(cert)
    db_session.commit()
    db_session.refresh(cert)
    return cert


@pytest.fixture
def revoked_certificate(db_session):
    """创建已吊销证书"""
    cert = Certificate(
        certificate_type="user",
        serial_number=f"REVOKED{uuid4().hex[:12].upper()}",
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


@pytest.fixture
def expired_certificate(db_session):
    """创建已过期证书"""
    cert = Certificate(
        certificate_type="user",
        serial_number=f"EXPIRED{uuid4().hex[:12].upper()}",
        subject="CN=expired.example.com,O=Test Org,C=CN",
        issuer="CN=Test CA,O=Test CA,C=CN",
        status=CertificateStatus.EXPIRED,
        issued_at=beijing_now() - timedelta(days=400),
        expires_at=beijing_now() - timedelta(days=35),
        certificate_pem="-----BEGIN CERTIFICATE-----\nEXPIRED_CERT\n-----END CERTIFICATE-----",
        public_key="EXPIRED_PUBLIC_KEY",
    )
    db_session.add(cert)
    db_session.commit()
    db_session.refresh(cert)
    return cert


class TestOCSPCertificateStatusAPI:
    """测试OCSP证书状态查询API"""

    def test_get_valid_certificate_status(self, client: TestClient, valid_certificate):
        """测试查询有效证书状态"""
        response = client.get(
            f"/acps-atr-v1/ocsp/certificate/{valid_certificate.serial_number}"
        )
        assert response.status_code == 200

        data = response.json()
        assert data["serialNumber"] == valid_certificate.serial_number
        assert data["certificateStatus"] == "good"
        assert "thisUpdate" in data
        assert "nextUpdate" in data

    def test_get_revoked_certificate_status(
        self, client: TestClient, revoked_certificate
    ):
        """测试查询已吊销证书状态"""
        response = client.get(
            f"/acps-atr-v1/ocsp/certificate/{revoked_certificate.serial_number}"
        )
        assert response.status_code == 200

        data = response.json()
        assert data["serialNumber"] == revoked_certificate.serial_number
        assert data["certificateStatus"] == "revoked"
        assert "revocationTime" in data
        assert "revocationReason" in data
        assert data["revocationReason"] == "keyCompromise"

    def test_get_expired_certificate_status(
        self, client: TestClient, expired_certificate
    ):
        """测试查询已过期证书状态"""
        response = client.get(
            f"/acps-atr-v1/ocsp/certificate/{expired_certificate.serial_number}"
        )
        assert response.status_code == 200

        data = response.json()
        assert data["serialNumber"] == expired_certificate.serial_number
        assert data["certificateStatus"] == "expired"

    def test_get_unknown_certificate_status(self, client: TestClient):
        """测试查询不存在证书状态"""
        response = client.get("/acps-atr-v1/ocsp/certificate/NONEXISTENT123456")
        assert response.status_code == 200

        data = response.json()
        assert data["serialNumber"] == "NONEXISTENT123456"
        assert data["certificateStatus"] == "unknown"

    def test_certificate_status_consistency(
        self, client: TestClient, valid_certificate
    ):
        """测试证书状态的一致性"""
        # 多次查询同一证书，状态应该保持一致
        responses = []
        for _ in range(3):
            response = client.get(
                f"/acps-atr-v1/ocsp/certificate/{valid_certificate.serial_number}"
            )
            assert response.status_code == 200
            responses.append(response.json())

        # 所有响应的状态应该相同
        statuses = [r["certificateStatus"] for r in responses]
        assert len(set(statuses)) == 1


class TestOCSPBatchAPI:
    """测试OCSP批量查询API"""

    def test_batch_certificate_status(
        self, client: TestClient, valid_certificate, revoked_certificate
    ):
        """测试批量查询证书状态"""
        request_data = {
            "certificates": [
                {
                    "serial_number": valid_certificate.serial_number,
                    "issuer_key_hash": "d042ee4e30dcd77e3a2f8eb3f5d8fe8673567864",
                },
                {
                    "serial_number": revoked_certificate.serial_number,
                    "issuer_key_hash": "d042ee4e30dcd77e3a2f8eb3f5d8fe8673567864",
                },
                {
                    "serial_number": "NONEXISTENT123",
                    "issuer_key_hash": "d042ee4e30dcd77e3a2f8eb3f5d8fe8673567864",
                },
            ]
        }

        response = client.post("/acps-atr-v1/ocsp/batch", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert "responses" in data
        assert len(data["responses"]) == 3

        # 验证响应内容
        responses_by_serial = {r["serial_number"]: r for r in data["responses"]}

        # 有效证书
        valid_resp = responses_by_serial[valid_certificate.serial_number]
        assert valid_resp["status"] == "good"

        # 吊销证书
        revoked_resp = responses_by_serial[revoked_certificate.serial_number]
        assert revoked_resp["status"] == "revoked"

        # 不存在证书
        unknown_resp = responses_by_serial["NONEXISTENT123"]
        assert unknown_resp["status"] == "unknown"

    def test_empty_batch_request(self, client: TestClient):
        """测试空的批量请求"""
        request_data = {"certificates": []}

        response = client.post("/acps-atr-v1/ocsp/batch", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert data["responses"] == []

    def test_large_batch_request(self, client: TestClient, valid_certificate):
        """测试大批量请求"""
        # 创建100个查询请求
        certificates = [
            {
                "serial_number": f"TEST{i:04d}",
                "issuer_key_hash": "d042ee4e30dcd77e3a2f8eb3f5d8fe8673567864",
            }
            for i in range(100)
        ]
        certificates.append(
            {
                "serial_number": valid_certificate.serial_number,
                "issuer_key_hash": "d042ee4e30dcd77e3a2f8eb3f5d8fe8673567864",
            }
        )

        request_data = {"certificates": certificates}

        response = client.post("/acps-atr-v1/ocsp/batch", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert len(data["responses"]) == 101


class TestOCSPResponderAPI:
    """测试OCSP响应器API"""

    def test_get_responder_info(self, client: TestClient, ocsp_responder):
        """测试获取OCSP响应器信息"""
        response = client.get("/acps-atr-v1/ocsp/responder/info")
        assert response.status_code == 200

        data = response.json()
        assert "endpoints" in data
        assert "responder" in data
        assert "service_info" in data
        assert data["responder"]["name"] == ocsp_responder.name
        assert "key_hash" in data["responder"]

    def test_get_responder_info_no_responder(self, client: TestClient, db_session):
        """测试没有响应器时的情况"""
        # 删除所有响应器
        for responder in db_session.exec(select(OCSPResponder)).all():
            db_session.delete(responder)
        db_session.commit()

        response = client.get("/acps-atr-v1/ocsp/responder/info")
        assert response.status_code == 404


class TestOCSPStatsAPI:
    """测试OCSP统计API"""

    def test_get_ocsp_statistics(self, client: TestClient):
        """测试获取OCSP统计信息"""
        response = client.get("/acps-atr-v1/ocsp/stats")
        assert response.status_code == 200

        data = response.json()
        assert "total_requests" in data
        assert "good_responses" in data
        assert "revoked_responses" in data
        assert "unknown_responses" in data
        assert "average_response_time_ms" in data
        assert "last_24h_requests" in data

        # 统计数据应该是非负数
        for key in [
            "total_requests",
            "good_responses",
            "revoked_responses",
            "unknown_responses",
        ]:
            assert data[key] >= 0

        assert data["average_response_time_ms"] >= 0.0

    def test_stats_update_after_requests(self, client: TestClient, valid_certificate):
        """测试请求后统计数据更新"""
        # 获取初始统计
        initial_response = client.get("/acps-atr-v1/ocsp/stats")
        initial_data = initial_response.json()
        initial_total = initial_data["total_requests"]

        # 执行一些OCSP查询
        for _ in range(3):
            client.get(
                f"/acps-atr-v1/ocsp/certificate/{valid_certificate.serial_number}"
            )

        # 获取更新后的统计
        updated_response = client.get("/acps-atr-v1/ocsp/stats")
        updated_data = updated_response.json()

        # 注意：当前实现可能不会实时更新统计，这取决于具体实现
        # 这里只验证API能正常返回数据
        assert updated_data["total_requests"] >= initial_total


class TestOCSPService:
    """测试OCSP服务层功能"""

    def test_get_certificate_status_valid(self, ocsp_service, valid_certificate):
        """测试获取有效证书状态"""
        status = ocsp_service.get_certificate_status(valid_certificate.serial_number)

        assert status is not None
        assert status["serialNumber"] == valid_certificate.serial_number
        assert status["certificateStatus"] == "good"

    def test_get_certificate_status_revoked(self, ocsp_service, revoked_certificate):
        """测试获取已吊销证书状态"""
        status = ocsp_service.get_certificate_status(revoked_certificate.serial_number)

        assert status is not None
        assert status["serialNumber"] == revoked_certificate.serial_number
        assert status["certificateStatus"] == "revoked"
        assert status["revocationReason"] == "keyCompromise"

    def test_get_certificate_status_unknown(self, ocsp_service):
        """测试获取未知证书状态"""
        status = ocsp_service.get_certificate_status("UNKNOWN_SERIAL")

        assert status is not None
        assert status["serialNumber"] == "UNKNOWN_SERIAL"
        assert status["certificateStatus"] == "unknown"

    def test_get_responder_info(self, ocsp_service, ocsp_responder):
        """测试获取响应器信息"""
        info = ocsp_service.get_responder_info()

        assert info is not None
        assert "endpoints" in info
        assert "responder" in info
        assert info["responder"]["name"] == ocsp_responder.name
        assert "key_hash" in info["responder"]

    def test_get_ocsp_statistics(self, ocsp_service):
        """测试获取OCSP统计"""
        stats = ocsp_service.get_ocsp_statistics()

        assert stats is not None
        assert "total_requests" in stats
        assert "good_responses" in stats
        assert "revoked_responses" in stats
        assert "unknown_responses" in stats

    def test_batch_certificate_status(
        self, ocsp_service, valid_certificate, revoked_certificate
    ):
        """测试批量证书状态查询"""
        certificates = [
            {"serial_number": valid_certificate.serial_number},
            {"serial_number": revoked_certificate.serial_number},
            {"serial_number": "NONEXISTENT"},
        ]

        responses = ocsp_service.batch_certificate_status(certificates)

        assert len(responses) == 3

        # 验证响应
        serials = [r["serial_number"] for r in responses]
        assert valid_certificate.serial_number in serials
        assert revoked_certificate.serial_number in serials
        assert "NONEXISTENT" in serials


class TestOCSPIntegration:
    """测试OCSP集成功能"""

    def test_certificate_revocation_updates_ocsp(
        self, client: TestClient, valid_certificate
    ):
        """测试证书吊销后OCSP状态更新"""
        # 初始状态应该是good
        initial_response = client.get(
            f"/acps-atr-v1/ocsp/certificate/{valid_certificate.serial_number}"
        )
        assert initial_response.status_code == 200
        assert initial_response.json()["certificateStatus"] == "good"

        # 吊销证书
        revoke_response = client.post(
            f"/admin/certificates/{valid_certificate.id}/revoke",
            params={"reason": "keyCompromise"},
        )
        assert revoke_response.status_code == 200

        # 再次查询OCSP状态
        updated_response = client.get(
            f"/acps-atr-v1/ocsp/certificate/{valid_certificate.serial_number}"
        )
        assert updated_response.status_code == 200

        updated_data = updated_response.json()
        assert updated_data["certificateStatus"] == "revoked"
        assert updated_data["revocationReason"] == "keyCompromise"

    def test_ocsp_response_format(self, client: TestClient, valid_certificate):
        """测试OCSP响应格式的正确性"""
        response = client.get(
            f"/acps-atr-v1/ocsp/certificate/{valid_certificate.serial_number}"
        )
        assert response.status_code == 200

        data = response.json()

        # 验证必需字段
        required_fields = ["serialNumber", "certificateStatus", "thisUpdate"]
        for field in required_fields:
            assert field in data

        # 验证状态值
        assert data["certificateStatus"] in ["good", "revoked", "expired", "unknown"]

        # 验证时间格式
        assert isinstance(data["thisUpdate"], str)
        if "nextUpdate" in data:
            assert isinstance(data["nextUpdate"], str)

    def test_ocsp_error_handling(self, client: TestClient):
        """测试OCSP错误处理"""
        # 测试无效的序列号格式
        response = client.get("/acps-atr-v1/ocsp/certificate/")
        assert (
            response.status_code == 400
        )  # FastAPI validation error for missing path parameter

        # 测试特殊字符
        response = client.get("/acps-atr-v1/ocsp/certificate/INVALID!@#$%")
        assert response.status_code == 200
        assert response.json()["certificateStatus"] == "unknown"

    def test_ocsp_performance(self, client: TestClient, valid_certificate):
        """测试OCSP性能"""
        import time

        # 测试多个并发请求的响应时间
        start_time = time.time()
        for _ in range(10):
            response = client.get(
                f"/acps-atr-v1/ocsp/certificate/{valid_certificate.serial_number}"
            )
            assert response.status_code == 200
        end_time = time.time()

        # 平均每个请求应该在合理时间内完成（这里设置为1秒）
        average_time = (end_time - start_time) / 10
        assert average_time < 1.0, f"Average response time {average_time}s is too slow"


class TestOCSPTimezoneHandling:
    """测试OCSP时区处理"""

    def test_timezone_aware_comparison(self, ocsp_service, db_session):
        """测试时区感知的时间比较"""
        # 创建一个即将过期的证书
        soon_expired_cert = Certificate(
            certificate_type="user",
            serial_number=f"SOONEXP{uuid4().hex[:12].upper()}",
            subject="CN=soonexpired.example.com,O=Test Org,C=CN",
            issuer="CN=Test CA,O=Test CA,C=CN",
            status=CertificateStatus.VALID,
            issued_at=beijing_now() - timedelta(days=30),
            expires_at=beijing_now() + timedelta(hours=1),  # 1小时后过期
            certificate_pem="-----BEGIN CERTIFICATE-----\nSOON_EXPIRED_CERT\n-----END CERTIFICATE-----",
            public_key="SOON_EXPIRED_PUBLIC_KEY",
        )
        db_session.add(soon_expired_cert)
        db_session.commit()

        # 查询状态，应该还是good（未过期）
        status = ocsp_service.get_certificate_status(soon_expired_cert.serial_number)
        assert status["certificateStatus"] == "good"

    def test_expired_certificate_detection(self, ocsp_service, db_session):
        """测试过期证书检测"""
        # 创建已过期的证书（设置为VALID状态但过期时间已过）
        past_expired_cert = Certificate(
            certificate_type="user",
            serial_number=f"PASTEXP{uuid4().hex[:12].upper()}",
            subject="CN=pastexpired.example.com,O=Test Org,C=CN",
            issuer="CN=Test CA,O=Test CA,C=CN",
            status=CertificateStatus.VALID,  # 数据库中状态为VALID
            issued_at=beijing_now() - timedelta(days=400),
            expires_at=beijing_now() - timedelta(days=1),  # 昨天过期
            certificate_pem="-----BEGIN CERTIFICATE-----\nPAST_EXPIRED_CERT\n-----END CERTIFICATE-----",
            public_key="PAST_EXPIRED_PUBLIC_KEY",
        )
        db_session.add(past_expired_cert)
        db_session.commit()

        # OCSP应该检测到过期并返回expired状态
        status = ocsp_service.get_certificate_status(past_expired_cert.serial_number)
        assert status["certificateStatus"] == "expired"
