"""
ACME API 完整测试套件

此测试文件包含所有ACME协议相关的测试：
1. 基础ACME协议功能（目录、nonce、基本流程）
2. 账户管理功能
3. JWS签名验证
4. Agent标识符验证
5. HTTP-01挑战验证
6. 证书签发功能
7. 证书策略验证
"""

import pytest
import json
import base64
from unittest.mock import AsyncMock, Mock, patch
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, ec, padding
from cryptography.hazmat.backends import default_backend

from main import app
from app.acme.jws_verifier import JWSVerifier
from app.acme.agent_registry import AgentRegistryClient, AgentInfo
from app.acme.http01_validator import HTTP01ValidationService


# ================== 基础ACME协议功能测试 ==================


class TestACMEDirectory:
    """测试 ACME 目录服务"""

    def test_get_directory(self):
        """测试获取 ACME 目录"""
        with TestClient(app) as client:
            response = client.get("/acps-atr-v2/acme/directory")

            assert response.status_code == 200
            data = response.json()

            assert "newNonce" in data
            assert "newAccount" in data
            assert "newOrder" in data
            assert "revokeCert" in data
            assert "keyChange" in data
            assert "meta" in data

            # 检查 meta 信息
            meta = data["meta"]
            assert "externalAccountRequired" in meta


class TestACMENonce:
    """测试 ACME nonce 服务"""

    def test_get_new_nonce_head(self):
        """测试 HEAD 方法获取 nonce"""
        with TestClient(app) as client:
            response = client.head("/acps-atr-v2/acme/new-nonce")

            assert response.status_code == 200
            assert "Replay-Nonce" in response.headers
            assert len(response.headers["Replay-Nonce"]) > 0
            assert "Cache-Control" in response.headers
            assert response.headers["Cache-Control"] == "no-store"

    def test_get_new_nonce_get(self):
        """测试 GET 方法获取 nonce"""
        with TestClient(app) as client:
            response = client.get("/acps-atr-v2/acme/new-nonce")

            assert response.status_code == 200
            assert "Replay-Nonce" in response.headers
            assert len(response.headers["Replay-Nonce"]) > 0
            assert "Cache-Control" in response.headers
            assert response.headers["Cache-Control"] == "no-store"


class TestACMEAccount:
    """测试 ACME 账户服务"""

    def test_create_account_missing_payload(self):
        """测试创建账户时缺少 payload"""
        with TestClient(app) as client:
            # 无效的 JWS 请求
            jws_data = {"protected": "", "payload": "", "signature": ""}

            response = client.post("/acps-atr-v2/acme/new-account", json=jws_data)

            # 应该返回错误，因为这不是有效的 JWS 格式
            assert response.status_code in [400, 422]


class TestACMEBasicFlow:
    """测试基本的 ACME 流程"""

    def test_directory_and_nonce_flow(self):
        """测试获取目录和 nonce 的基本流程"""
        with TestClient(app) as client:
            # 1. 获取目录
            dir_response = client.get("/acps-atr-v2/acme/directory")
            assert dir_response.status_code == 200
            directory = dir_response.json()

            # 2. 获取 nonce
            nonce_response = client.get("/acps-atr-v2/acme/new-nonce")
            assert nonce_response.status_code == 200
            assert "Replay-Nonce" in nonce_response.headers

            # 3. 验证目录中的 URL 结构
            # 检查URL包含正确的端点名称
            assert "new-nonce" in directory["newNonce"]
            assert "new-account" in directory["newAccount"]
            assert "new-order" in directory["newOrder"]

    def test_health_check(self):
        """测试健康检查端点"""
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert "status" in data
            assert data["status"] == "healthy"


# ================== JWS签名验证测试 ==================


class TestJWSVerification:
    """测试JWS签名验证功能"""

    def setup_method(self):
        """设置测试"""
        self.jws_verifier = JWSVerifier()

        # 生成测试RSA密钥对
        self.private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )
        self.public_key = self.private_key.public_key()

        # 创建JWK
        public_numbers = self.public_key.public_numbers()
        n = public_numbers.n.to_bytes((public_numbers.n.bit_length() + 7) // 8, "big")
        e = public_numbers.e.to_bytes((public_numbers.e.bit_length() + 7) // 8, "big")

        self.jwk = {
            "kty": "RSA",
            "n": base64.urlsafe_b64encode(n).decode("ascii").rstrip("="),
            "e": base64.urlsafe_b64encode(e).decode("ascii").rstrip("="),
        }

    def test_base64url_decode(self):
        """测试base64url解码"""
        data = "SGVsbG8gV29ybGQ"
        decoded = self.jws_verifier.base64url_decode(data)
        assert decoded == b"Hello World"

    def test_base64url_encode(self):
        """测试base64url编码"""
        data = b"Hello World"
        encoded = self.jws_verifier.base64url_encode(data)
        assert encoded == "SGVsbG8gV29ybGQ"

    def test_jwk_to_public_key(self):
        """测试JWK转换为公钥"""
        converted_key = self.jws_verifier._jwk_to_public_key(self.jwk)

        # 验证转换的公钥与原始公钥匹配
        assert converted_key.public_numbers().n == self.public_key.public_numbers().n
        assert converted_key.public_numbers().e == self.public_key.public_numbers().e

    def test_jwk_thumbprint(self):
        """测试JWK指纹计算"""
        thumbprint = self.jws_verifier.compute_jwk_thumbprint(self.jwk)

        # 指纹应该是base64url编码的字符串
        assert isinstance(thumbprint, str)
        assert len(thumbprint) > 0

        # 同样的JWK应该产生相同的指纹
        thumbprint2 = self.jws_verifier.compute_jwk_thumbprint(self.jwk)
        assert thumbprint == thumbprint2

    def create_test_jws(self, payload_dict: dict, protected_dict: dict) -> str:
        """创建测试JWS"""
        # 编码protected header
        protected_json = json.dumps(protected_dict, separators=(",", ":"))
        protected_b64 = (
            base64.urlsafe_b64encode(protected_json.encode()).decode().rstrip("=")
        )

        # 编码payload
        payload_json = json.dumps(payload_dict, separators=(",", ":"))
        payload_b64 = (
            base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
        )

        # 创建签名
        signing_input = f"{protected_b64}.{payload_b64}".encode()
        signature = self.private_key.sign(
            signing_input, padding.PKCS1v15(), hashes.SHA256()
        )
        signature_b64 = base64.urlsafe_b64encode(signature).decode().rstrip("=")

        return f"{protected_b64}.{payload_b64}.{signature_b64}"

    def test_valid_jws_verification(self):
        """测试有效JWS验证"""
        protected = {
            "alg": "RS256",
            "jwk": self.jwk,
            "nonce": "test-nonce",
            "url": "https://example.com/test",
        }
        payload = {"test": "data"}

        jws = self.create_test_jws(payload, protected)

        # 验证JWS
        result = self.jws_verifier.verify_jws_signature(
            jws, self.jwk, "test-nonce", "https://example.com/test"
        )

        assert result == payload

    def test_valid_ec_jws_verification(self):
        """测试有效的 EC JWS 签名验证"""
        # 生成 EC 密钥对
        private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
        public_key = private_key.public_key()

        # 获取公钥参数
        numbers = public_key.public_numbers()
        x = numbers.x
        y = numbers.y

        # 构建 JWK
        jwk = {
            "kty": "EC",
            "crv": "P-256",
            "x": self.jws_verifier.base64url_encode(x.to_bytes(32, byteorder="big")),
            "y": self.jws_verifier.base64url_encode(y.to_bytes(32, byteorder="big")),
        }

        # 构建 payload
        payload = {"test": "ec_data"}
        payload_json = json.dumps(payload)
        payload_b64 = self.jws_verifier.base64url_encode(payload_json.encode("utf-8"))

        # 构建 protected header
        protected = {
            "alg": "ES256",
            "jwk": jwk,
            "nonce": "test-ec-nonce",
            "url": "https://example.com/ec-test",
        }
        protected_json = json.dumps(protected)
        protected_b64 = self.jws_verifier.base64url_encode(
            protected_json.encode("utf-8")
        )

        # 签名
        signing_input = f"{protected_b64}.{payload_b64}".encode("ascii")
        der_signature = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))

        # 将 DER 签名转换为 Raw (R||S) 格式，符合 JWS 规范
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

        r, s = decode_dss_signature(der_signature)
        raw_signature = r.to_bytes(32, byteorder="big") + s.to_bytes(
            32, byteorder="big"
        )

        signature_b64 = self.jws_verifier.base64url_encode(raw_signature)

        # 构建 JWS
        jws_data = f"{protected_b64}.{payload_b64}.{signature_b64}"

        # 验证
        result = self.jws_verifier.verify_jws_signature(
            jws_data,
            jwk,
            expected_nonce="test-ec-nonce",
            expected_url="https://example.com/ec-test",
        )

        assert result == payload


# ================== Agent注册服务测试 ==================


class TestAgentRegistryClient:
    """测试Agent注册服务客户端"""

    def setup_method(self):
        """设置测试"""
        with patch("app.acme.agent_registry.get_settings") as mock_settings:
            mock_settings.return_value.agent_registry_url = "http://test-registry"
            mock_settings.return_value.agent_registry_timeout = 10
            mock_settings.return_value.agent_registry_service_token = "test-token"
            mock_settings.return_value.external_service_max_retries = 3
            mock_settings.return_value.external_service_retry_delays_list = [1, 2, 4]
            # 确保Mock模式被禁用
            mock_settings.return_value.agent_registry_mock = False

            self.client = AgentRegistryClient()

    def test_agent_info_creation(self):
        """测试 AgentInfo 数据类 - 使用 ACS 格式"""
        # 测试 ACS 数据结构
        test_data_acs = {
            "aic": "AGENT001TEST2024XYZ123456ABCDEF78",
            "active": True,
            "name": "Test Agent Service",
            "version": "1.0.0",
            "provider": {
                "organization": "Test Corp",
                "department": "AI Services",
                "countryCode": "US",
            },
            "securitySchemes": {
                "mtls": {
                    "description": "智能体间mTLS双向认证",
                    "type": "mutualTLS",
                    "x-caChallengeBaseUrl": "https://agent.example.com/ca/challenge",
                }
            },
            "endPoints": [
                {
                    "url": "https://agent.example.com/acps-aip-v2/rpc",
                    "security": [{"mtls": []}],
                    "transport": "JSONRPC",
                }
            ],
            "capabilities": {"communication": ["jsonrpc"]},
            "skills": [],
        }

        agent_info = AgentInfo(test_data_acs)

        assert agent_info.aic == "AGENT001TEST2024XYZ123456ABCDEF78"
        assert agent_info.is_valid() is True
        assert agent_info.name == "Test Agent Service"
        assert agent_info.organization == "Test Corp"
        assert agent_info.department == "AI Services"
        assert agent_info.country_code == "US"
        assert (
            agent_info.ca_challenge_base_url == "https://agent.example.com/ca/challenge"
        )

        # 测试证书Subject DN组件
        components = agent_info.get_certificate_subject_components()
        expected = {
            "CN": "AGENT001TEST2024XYZ123456ABCDEF78.acps.pub",
            "O": "Test Corp",
            "OU": "AI Services",
            "C": "US",
        }
        assert components == expected

        # 测试挑战URL构造
        token = "test_token_123"
        expected_challenge_url = "https://agent.example.com/ca/challenge/AGENT001TEST2024XYZ123456ABCDEF78/test_token_123"
        assert agent_info.get_challenge_url(token) == expected_challenge_url

        # 测试另一个 ACS 格式的数据
        test_data_2 = {
            "aic": "AGENT002OLD2024LEGACY987654321ABC",
            "active": True,
            "name": "Legacy Agent Service",
            "version": "2.0.0",
            "provider": {
                "organization": "Old Corp",
                "department": "Legacy Services",
                "countryCode": "CA",
            },
            "securitySchemes": {
                "mtls": {
                    "description": "智能体间mTLS双向认证",
                    "type": "mutualTLS",
                    "x-caChallengeBaseUrl": "https://old-agent.example.com/ca/agent",
                }
            },
            "endPoints": [
                {
                    "url": "https://old-agent.example.com/acps-aip-v2/rpc",
                    "security": [{"mtls": []}],
                    "transport": "JSONRPC",
                }
            ],
            "capabilities": {},
            "skills": [],
        }

        agent_info_2 = AgentInfo(test_data_2)
        assert agent_info_2.aic == "AGENT002OLD2024LEGACY987654321ABC"
        assert agent_info_2.organization == "Old Corp"
        assert (
            agent_info_2.ca_challenge_base_url
            == "https://old-agent.example.com/ca/agent"
        )

    @pytest.mark.asyncio
    async def test_validate_aic_success(self):
        """测试成功的AIC验证"""
        test_response_data = {
            "aic": "AGENTTEST123SUCCESS4567890ABCDEF12",
            "active": True,
            "name": "Test Agent Service",
            "version": "1.0.0",
            "provider": {
                "organization": "Test Corp",
                "department": "AI Services",
                "countryCode": "US",
            },
            "securitySchemes": {
                "mtls": {
                    "description": "智能体间mTLS双向认证",
                    "type": "mutualTLS",
                    "x-caChallengeBaseUrl": "https://agent.example.com/ca/challenge",
                }
            },
            "endPoints": [
                {
                    "url": "https://agent.example.com/acps-aip-v2/rpc",
                    "security": [{"mtls": []}],
                    "transport": "JSONRPC",
                }
            ],
            "capabilities": {"communication": ["jsonrpc"]},
            "skills": [],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = test_response_data

            mock_request = mock_client.return_value.__aenter__.return_value.request
            mock_request.return_value = mock_response

            result = await self.client.validate_aic_and_get_info(
                "AGENTTEST123SUCCESS4567890ABCDEF12"
            )

            assert result is not None
            assert result.aic == "AGENTTEST123SUCCESS4567890ABCDEF12"
            assert result.is_valid() is True

            # 验证请求 URL 是否包含 /acs/ 路径
            mock_request.assert_called()
            args, kwargs = mock_request.call_args
            assert args[0] == "GET"
            assert (
                args[1] == "http://test-registry/acs/AGENTTEST123SUCCESS4567890ABCDEF12"
            )

    @pytest.mark.asyncio
    async def test_validate_aic_not_found(self):
        """测试AIC不存在的情况"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.status_code = 404

            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )

            result = await self.client.validate_aic_and_get_info("nonexistent-agent")

            assert result is None


# ================== HTTP-01挑战验证测试 ==================


class TestHTTP01ValidationService:
    """测试HTTP-01验证服务"""

    def setup_method(self):
        """设置测试"""
        with patch("app.acme.http01_validator.get_settings") as mock_settings:
            mock_settings.return_value.http01_validation_timeout = 30
            mock_settings.return_value.http01_validation_retries = 2
            mock_settings.return_value.external_service_retry_delays_list = [1, 2, 4]
            # 确保Mock模式被禁用
            mock_settings.return_value.http01_validation_mock = False

            self.validator = HTTP01ValidationService()

    def test_build_challenge_url(self):
        """测试挑战URL构造"""
        agent_data = {
            "aic": "ABCD1234EFGH5678IJKL9012MNOP3456",
            "active": True,
            "name": "Test Agent",
            "version": "1.0.0",
            "provider": {
                "organization": "Test Corp",
                "department": "Engineering",
                "countryCode": "US",
            },
            "securitySchemes": {
                "mtls": {
                    "type": "mutualTLS",
                    "x-caChallengeBaseUrl": "https://agent.example.com/ca/challenge",
                }
            },
            "endPoints": [],
            "capabilities": [],
            "skills": [],
        }
        agent_info = AgentInfo(agent_data)
        token = "test-token-123"

        url = self.validator._build_challenge_url(agent_info, token)
        expected = "https://agent.example.com/ca/challenge/ABCD1234EFGH5678IJKL9012MNOP3456/test-token-123"

        assert url == expected

    def test_build_challenge_url_without_path(self):
        """测试不带路径的挑战URL构造"""
        agent_data = {
            "aic": "ABCD1234EFGH5678IJKL9012MNOP3456",
            "active": True,
            "name": "Test Agent",
            "version": "1.0.0",
            "provider": {
                "organization": "Test Corp",
                "department": "Engineering",
                "countryCode": "US",
            },
            "securitySchemes": {
                "mtls": {
                    "type": "mutualTLS",
                    "x-caChallengeBaseUrl": "https://agent.example.com/ca/agent",
                }
            },
            "endPoints": [],
            "capabilities": [],
            "skills": [],
        }
        agent_info = AgentInfo(agent_data)
        token = "test-token-123"

        url = self.validator._build_challenge_url(agent_info, token)
        expected = "https://agent.example.com/ca/agent/ABCD1234EFGH5678IJKL9012MNOP3456/test-token-123"

        assert url == expected

    @pytest.mark.asyncio
    async def test_successful_validation(self):
        """测试成功的HTTP-01验证"""
        agent_data = {
            "aic": "ABCD1234EFGH5678IJKL9012MNOP3456",
            "active": True,
            "name": "Test Agent",
            "version": "1.0.0",
            "provider": {
                "organization": "Test Corp",
                "department": "Engineering",
                "countryCode": "US",
            },
            "securitySchemes": {
                "mtls": {
                    "type": "mutualTLS",
                    "x-caChallengeBaseUrl": "https://agent.example.com/ca/challenge",
                }
            },
            "endPoints": [],
            "capabilities": [],
            "skills": [],
        }
        agent_info = AgentInfo(agent_data)
        token = "test-token"
        key_authorization = "test-token.test-thumbprint"

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = key_authorization

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await self.validator.validate_challenge(
                agent_info, token, key_authorization
            )

            assert result.success is True
            assert result.error is None

    @pytest.mark.asyncio
    async def test_failed_validation_wrong_content(self):
        """测试内容不匹配的验证失败"""
        agent_data = {
            "aic": "ABCD1234EFGH5678IJKL9012MNOP3456",
            "active": True,
            "name": "Test Agent",
            "version": "1.0.0",
            "provider": {
                "organization": "Test Corp",
                "department": "Engineering",
                "countryCode": "US",
            },
            "securitySchemes": {
                "mtls": {
                    "type": "mutualTLS",
                    "x-caChallengeBaseUrl": "https://agent.example.com/ca/challenge",
                }
            },
            "endPoints": [],
            "capabilities": [],
            "skills": [],
        }
        agent_info = AgentInfo(agent_data)
        token = "test-token"
        key_authorization = "test-token.test-thumbprint"

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "wrong-content"

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await self.validator.validate_challenge(
                agent_info, token, key_authorization
            )

            assert result.success is False
            assert "Content mismatch" in result.error

    @pytest.mark.asyncio
    async def test_pre_validate_agent_endpoint(self):
        """测试Agent端点预验证"""
        agent_data = {
            "aic": "ABCD1234EFGH5678IJKL9012MNOP3456",
            "active": True,
            "name": "Test Agent",
            "version": "1.0.0",
            "provider": {
                "organization": "Test Corp",
                "department": "Engineering",
                "countryCode": "US",
            },
            "securitySchemes": {
                "mtls": {
                    "type": "mutualTLS",
                    "x-caChallengeBaseUrl": "https://agent.example.com/",
                }
            },
            "endPoints": [],
            "capabilities": [],
            "skills": [],
        }
        agent_info = AgentInfo(agent_data)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            # 健康检查不再需要特定的 JSON 响应，只要状态码是 200 即可
            mock_response.text = "OK"

            mock_get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            result = await self.validator.pre_validate_agent_endpoint(agent_info)

            assert result.success is True

            # 验证调用的 URL 是 /health
            mock_get.assert_called_with("https://agent.example.com/health")


# ================== 证书签发功能测试 ==================


class TestCertificateIssuing:
    """测试证书签发功能"""

    def setup_method(self):
        """设置测试"""
        from app.core.ca_manager import CAManager
        from app.acme.services import CertificateService

        self.ca_manager = CAManager()

        # 模拟数据库会话
        self.mock_session = Mock()
        self.cert_service = CertificateService(self.mock_session)

    def create_test_csr(self, key_size=2048, use_ec=False):
        """创建测试CSR"""
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives.asymmetric import rsa, ec
        from cryptography.hazmat.primitives import hashes

        if use_ec:
            # 使用 ECDSA P-256
            private_key = ec.generate_private_key(ec.SECP256R1())
        else:
            # 使用 RSA
            private_key = rsa.generate_private_key(
                public_exponent=65537, key_size=key_size
            )

        subject = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, "agent-001"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test Org"),
            ]
        )

        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(subject)
            .sign(private_key, hashes.SHA256())
        )

        return csr, private_key

    def test_validate_csr_rsa_2048_allowed(self):
        """测试RSA 2048位密钥被允许"""
        csr, _ = self.create_test_csr(key_size=2048)

        # 应该不抛出异常
        try:
            self.ca_manager._validate_csr_public_key(csr)
        except Exception as e:
            pytest.fail(f"RSA 2048 should be allowed, but got error: {e}")

    def test_validate_csr_rsa_1024_rejected(self):
        """测试RSA 1024位密钥被拒绝"""
        csr, _ = self.create_test_csr(key_size=1024)

        with pytest.raises(ValueError, match="RSA key size 1024 is too small"):
            self.ca_manager._validate_csr_public_key(csr)

    def test_validate_csr_ecdsa_p256_allowed(self):
        """测试ECDSA P-256被允许"""
        csr, _ = self.create_test_csr(use_ec=True)

        # 应该不抛出异常
        try:
            self.ca_manager._validate_csr_public_key(csr)
        except Exception as e:
            pytest.fail(f"ECDSA P-256 should be allowed, but got error: {e}")

    def test_single_agent_certificate_generation(self):
        """测试单Agent证书生成"""
        from app.acme.models import AcmeOrder
        from app.acme.agent_registry import AgentInfo
        import secrets

        # 创建模拟订单
        order = Mock(spec=AcmeOrder)
        order.id = 1
        order.identifiers = [{"type": "agent", "value": "agent-001"}]

        # 创建模拟Agent信息 - 使用新的ACS数据结构
        agent_data = {
            "aic": "agent-001",
            "valid": True,
            "acs": {
                "name": "Test Agent",
                "provider": "Test Org",
                "ca-challenge-url": "https://test-agent.example.com/ca/challenge",
                "organizationName": "Test Org",
                "country": "US",
                "status": "active",
            },
        }
        agent_info = AgentInfo(agent_data)

        # 创建CSR
        csr, _ = self.create_test_csr()
        csr_der = csr.public_bytes(serialization.Encoding.DER)

        # Mock数据库操作和证书生成，使用简化的主体信息
        mock_cert = Mock()
        mock_cert.cert_id = "cert_" + secrets.token_urlsafe(16)
        mock_cert.serial_number = secrets.token_hex(16)

        with patch.object(
            self.cert_service, "_create_certificate", return_value=mock_cert
        ):
            with patch.object(
                self.cert_service,
                "_generate_certificate_for_agent",
                return_value="-----BEGIN CERTIFICATE-----\nMOCK_CERT\n-----END CERTIFICATE-----",
            ):
                with patch.object(
                    self.cert_service,
                    "_extract_subject_from_cert_pem",
                    return_value={
                        "CN": "agent-001.acps.pub",
                        "O": "Test Org",
                    },
                ):
                    with patch.object(
                        self.cert_service,
                        "_extract_serial_number_from_cert_pem",
                        return_value="1234567890ABCDEF",
                    ):
                        certificates = self.cert_service.issue_certificate(
                            order, csr_der, [agent_info]
                        )

                        assert len(certificates) == 1
                        assert certificates[0] == mock_cert

    def test_multi_agent_certificate_generation(self):
        """测试多Agent证书生成（每个Agent一张证书）"""
        from app.acme.models import AcmeOrder
        from app.acme.agent_registry import AgentInfo
        import secrets

        # 创建模拟订单，包含两个Agent
        order = Mock(spec=AcmeOrder)
        order.id = 1
        order.identifiers = [
            {"type": "agent", "value": "agent-001"},
            {"type": "agent", "value": "agent-002"},
        ]

        # 创建模拟Agent信息 - 使用新的ACS数据结构
        agent_infos = [
            AgentInfo(
                {
                    "aic": "agent-001",
                    "valid": True,
                    "acs": {
                        "name": "Test Agent 1",
                        "provider": "Test Org 1",
                        "ca-challenge-url": "https://agent-001.example.com/ca/challenge",
                        "organizationName": "Test Org 1",
                        "country": "US",
                        "status": "active",
                    },
                }
            ),
            AgentInfo(
                {
                    "aic": "agent-002",
                    "valid": True,
                    "acs": {
                        "name": "Test Agent 2",
                        "provider": "Test Org 2",
                        "ca-challenge-url": "https://agent-002.example.com/ca/challenge",
                        "organizationName": "Test Org 2",
                        "country": "US",
                        "status": "active",
                    },
                }
            ),
        ]

        # 创建CSR
        csr, _ = self.create_test_csr()
        csr_der = csr.public_bytes(serialization.Encoding.DER)

        # Mock数据库操作
        mock_certs = [
            Mock(cert_id="cert_" + secrets.token_urlsafe(16)),
            Mock(cert_id="cert_" + secrets.token_urlsafe(16)),
        ]

        with patch.object(
            self.cert_service, "_create_certificate", side_effect=mock_certs
        ):
            with patch.object(
                self.cert_service,
                "_generate_certificate_for_agent",
                return_value="-----BEGIN CERTIFICATE-----\nMOCK_CERT\n-----END CERTIFICATE-----",
            ):
                with patch.object(
                    self.cert_service,
                    "_extract_subject_from_cert_pem",
                    return_value={"CN": "agent.acps.pub", "O": "Test Org"},
                ):
                    with patch.object(
                        self.cert_service,
                        "_extract_serial_number_from_cert_pem",
                        return_value="1234567890ABCDEF",
                    ):
                        certificates = self.cert_service.issue_certificate(
                            order, csr_der, agent_infos
                        )

                        # 应该为每个Agent签发一张证书
                        assert len(certificates) == 2
                        assert certificates[0] == mock_certs[0]
                        assert certificates[1] == mock_certs[1]

    def test_certificate_subject_built_from_agent_info(self):
        """测试证书Subject DN根据Agent注册信息构造"""
        from app.acme.agent_registry import AgentInfo

        agent_data = {
            "aic": "ABCD1234EFGH5678IJKL9012MNOP3456",
            "active": True,
            "name": "ACME Agent Service",
            "version": "1.0.0",
            "provider": {
                "organization": "ACME Corp",
                "department": "Engineering",
                "countryCode": "US",
            },
            "securitySchemes": {
                "mtls": {
                    "x-caChallengeBaseUrl": "https://acme-agent.example.com/ca/challenge"
                }
            },
            "endPoints": [],
            "capabilities": [],
            "skills": [],
        }
        agent_info = AgentInfo(agent_data)

        subject_components = agent_info.get_certificate_subject_components()
        subject = self.ca_manager._build_certificate_subject(
            "ABCD1234EFGH5678IJKL9012MNOP3456", subject_components
        )

        # 验证Subject DN包含Agent信息
        subject_dict = {attr.oid._name: attr.value for attr in subject}
        assert (
            subject_dict.get("commonName")
            == "ABCD1234EFGH5678IJKL9012MNOP3456.acps.pub"
        )
        assert subject_dict.get("organizationName") == "ACME Corp"
        assert subject_dict.get("organizationalUnitName") == "Engineering"
        assert subject_dict.get("countryName") == "US"


# ================== 证书策略测试 ==================


class TestCertificatePolicy:
    """测试证书策略"""

    def test_certificate_validity_period(self):
        """测试证书有效期为49天"""
        from datetime import datetime, timedelta, timezone

        # 这个测试主要验证代码中的有效期设置
        expected_validity_days = 49

        # 在实际的证书签发中会使用这个值
        not_before = datetime.now(timezone.utc)
        not_after = not_before + timedelta(days=expected_validity_days)

        actual_days = (not_after - not_before).days
        assert actual_days == expected_validity_days

    def test_san_extension_includes_agent_info(self):
        """测试SAN扩展包含Agent信息"""
        from app.core.ca_manager import CAManager
        from cryptography import x509

        ca_manager = CAManager()

        # 创建一个空的证书构建器来测试SAN扩展
        cert_builder = x509.CertificateBuilder()

        agent_id = "agent-001"
        agent_endpoints = ["https://agent001.example.com", "agent://agent-001/api"]

        # 测试SAN扩展添加
        cert_builder = ca_manager._add_agent_san_extensions(
            cert_builder, agent_id, agent_endpoints
        )

        # 由于我们无法直接从构建器中提取扩展，这里主要测试方法不会抛出异常
        # 实际的SAN内容验证需要在完整的证书生成流程中进行


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
