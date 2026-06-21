"""
Mock集成功能测试

验证AgentRegistryClient和HTTP01ValidationService的Mock模式是否正常工作
"""

import os
import pytest
from unittest.mock import patch

from app.acme.agent_registry import AgentRegistryClient, AgentInfo
from app.acme.http01_validator import HTTP01ValidationService
from app.acme.mock_data import MockDataGenerator


class TestMockIntegration:
    """Mock集成功能测试类"""

    @pytest.fixture(autouse=True)
    def setup_mock_mode(self):
        """为每个测试方法设置Mock模式"""
        # 保存原始环境变量
        original_agent_mock = os.environ.get("AGENT_REGISTRY_MOCK")
        original_http01_mock = os.environ.get("HTTP01_VALIDATION_MOCK")

        # 设置Mock模式
        os.environ["AGENT_REGISTRY_MOCK"] = "true"
        os.environ["HTTP01_VALIDATION_MOCK"] = "true"

        yield

        # 恢复原始环境变量
        if original_agent_mock is None:
            os.environ.pop("AGENT_REGISTRY_MOCK", None)
        else:
            os.environ["AGENT_REGISTRY_MOCK"] = original_agent_mock

        if original_http01_mock is None:
            os.environ.pop("HTTP01_VALIDATION_MOCK", None)
        else:
            os.environ["HTTP01_VALIDATION_MOCK"] = original_http01_mock

    @pytest.mark.asyncio
    async def test_agent_registry_mock_mode(self):
        """测试AgentRegistryClient的Mock功能"""
        with patch("app.acme.agent_registry.get_settings") as mock_settings:
            # Mock配置
            mock_settings.return_value.agent_registry_url = "http://test-registry"
            mock_settings.return_value.agent_registry_timeout = 10
            mock_settings.return_value.agent_registry_service_token = "test-token"
            mock_settings.return_value.external_service_max_retries = 3
            mock_settings.return_value.external_service_retry_delays_list = [1, 2, 4]
            mock_settings.return_value.agent_registry_mock = True

            client = AgentRegistryClient()

            # 验证Mock模式已启用
            assert client.is_mock_enabled is True

            test_aic = "test-agent-123"

            # 测试AIC验证和信息获取
            agent_info = await client.validate_aic_and_get_info(test_aic)
            assert agent_info is not None
            assert agent_info.aic == test_aic
            assert isinstance(agent_info.organization, str)
            assert len(agent_info.organization) > 0
            assert agent_info.country_code in MockDataGenerator.COUNTRIES
            assert agent_info.active in [True, False]

            # 测试证书请求注册
            reg_result = await client.register_certificate_request(
                test_aic, "order-123"
            )
            assert isinstance(reg_result, bool)

            # 测试证书签发通知
            notify_result = await client.notify_certificate_issued(
                test_aic, "order-123", "cert-456"
            )
            assert isinstance(notify_result, bool)

            # 测试所有权验证
            account_info = {"key_id": "test-key", "contact": "test@example.com"}
            ownership_result = await client.verify_agent_ownership(
                test_aic, account_info
            )
            assert isinstance(ownership_result, bool)

    @pytest.mark.asyncio
    async def test_http01_validation_mock_mode(self):
        """测试HTTP01ValidationService的Mock功能"""
        with patch("app.acme.http01_validator.get_settings") as mock_settings:
            # Mock配置
            mock_settings.return_value.http01_validation_timeout = 30
            mock_settings.return_value.http01_validation_retries = 2
            mock_settings.return_value.external_service_retry_delays_list = [1, 2, 4]
            mock_settings.return_value.http01_validation_mock = True

            validator = HTTP01ValidationService()

            # 验证Mock模式已启用
            assert validator.is_mock_enabled is True

            # 创建一个模拟的AgentInfo
            mock_generator = MockDataGenerator()
            agent_data = mock_generator.generate_agent_info("test-agent-456")
            agent_info = AgentInfo(agent_data)

            # 测试预验证
            pre_result = await validator.pre_validate_agent_endpoint(agent_info)
            assert hasattr(pre_result, "success")
            assert isinstance(pre_result.success, bool)

            # 测试挑战验证
            token = "test-token-123"
            key_auth = "test-key-authorization-456"

            validation_result = await validator.validate_challenge(
                agent_info, token, key_auth
            )
            assert hasattr(validation_result, "success")
            assert isinstance(validation_result.success, bool)
            assert hasattr(validation_result, "response_time")
            assert isinstance(validation_result.response_time, (int, float))

    @pytest.mark.asyncio
    async def test_mock_randomness(self):
        """测试Mock数据的随机性"""
        with patch("app.acme.agent_registry.get_settings") as mock_settings:
            # Mock配置
            mock_settings.return_value.agent_registry_url = "http://test-registry"
            mock_settings.return_value.agent_registry_timeout = 10
            mock_settings.return_value.agent_registry_service_token = "test-token"
            mock_settings.return_value.external_service_max_retries = 3
            mock_settings.return_value.external_service_retry_delays_list = [1, 2, 4]
            mock_settings.return_value.agent_registry_mock = True

            client = AgentRegistryClient()

            # 进行多次相同的请求，验证随机性
            organizations = []
            countries = []
            statuses = []

            for i in range(10):
                agent_info = await client.validate_aic_and_get_info(f"random-agent-{i}")
                if agent_info:
                    organizations.append(agent_info.organization)
                    countries.append(agent_info.country_code)
                    statuses.append("active" if agent_info.active else "inactive")

            # 验证有足够的随机性（不是所有值都相同）
            assert len(set(organizations)) > 1, "组织名称应该有随机性"
            # 由于国家和状态的选项有限，可能会有重复，但组织名称应该有较好的随机性

    @pytest.mark.asyncio
    async def test_http01_validation_randomness(self):
        """测试HTTP-01验证的随机性"""
        with patch("app.acme.http01_validator.get_settings") as mock_settings:
            # Mock配置
            mock_settings.return_value.http01_validation_timeout = 30
            mock_settings.return_value.http01_validation_retries = 2
            mock_settings.return_value.external_service_retry_delays_list = [1, 2, 4]
            mock_settings.return_value.http01_validation_mock = True

            validator = HTTP01ValidationService()

            results = []
            response_times = []

            # 进行多次验证，收集结果
            for i in range(10):
                mock_data = MockDataGenerator.generate_agent_info(f"http01-test-{i}")
                agent_info = AgentInfo(mock_data)

                result = await validator.validate_challenge(
                    agent_info, f"token-{i}", f"key-auth-{i}"
                )
                results.append(result.success)
                response_times.append(result.response_time)

            # 验证结果有变化（不是全部成功或全部失败）
            success_count = sum(results)
            assert (
                0 < success_count < len(results)
            ), f"验证结果应该有随机性，成功次数: {success_count}/{len(results)}"

            # 验证响应时间有变化
            assert len(set(response_times)) > 1, "响应时间应该有随机性"

    def test_mock_data_generator_agent_info(self):
        """测试MockDataGenerator生成Agent信息的功能"""
        generator = MockDataGenerator()

        # 测试生成指定AIC的Agent信息
        test_aic = "TESTAGENT123GENERATOR4567890ABCDE"
        agent_data = generator.generate_agent_info(test_aic)

        # 验证 ACS 格式的数据结构
        assert agent_data["aic"] == test_aic
        assert "active" in agent_data
        assert isinstance(agent_data["active"], bool)
        assert "name" in agent_data
        assert "version" in agent_data
        assert "provider" in agent_data
        assert "securitySchemes" in agent_data
        assert "endPoints" in agent_data
        assert "capabilities" in agent_data
        assert "skills" in agent_data

        # 验证 provider 信息结构
        provider = agent_data["provider"]
        required_provider_fields = [
            "organization",
            "department",
            "countryCode",
        ]
        for field in required_provider_fields:
            assert field in provider
            assert isinstance(provider[field], str)
            assert len(provider[field]) > 0

        # 验证 securitySchemes 结构
        security_schemes = agent_data["securitySchemes"]
        assert "mtls" in security_schemes
        mtls_config = security_schemes["mtls"]
        assert "x-caChallengeBaseUrl" in mtls_config
        assert isinstance(mtls_config["x-caChallengeBaseUrl"], str)
        assert len(mtls_config["x-caChallengeBaseUrl"]) > 0

        # 验证 endPoints 结构
        assert len(agent_data["endPoints"]) > 0
        endpoint = agent_data["endPoints"][0]
        assert "url" in endpoint
        assert "security" in endpoint
        assert "transport" in endpoint

    def test_mock_data_generator_randomness(self):
        """测试MockDataGenerator的随机性"""
        generator = MockDataGenerator()

        # 生成多个Agent信息
        agent_data_list = []
        for i in range(10):
            agent_data = generator.generate_agent_info(f"TESTAIC{i:030d}")
            agent_data_list.append(agent_data)

        # 提取组织名称（从 provider.organization）
        organizations = [data["provider"]["organization"] for data in agent_data_list]

        # 验证随机性
        unique_organizations = set(organizations)
        assert (
            len(unique_organizations) > 1
        ), f"应该生成不同的组织名称，实际: {organizations}"

    def test_mock_success_rates(self):
        """测试Mock功能的成功率"""
        generator = MockDataGenerator()

        # 测试端点验证成功率（应该约80%）
        endpoint_results = [
            generator.generate_endpoint_validation_result() for _ in range(100)
        ]
        success_rate = sum(endpoint_results) / len(endpoint_results)
        assert (
            0.6 <= success_rate <= 1.0
        ), f"端点验证成功率应该在合理范围内: {success_rate}"

        # 测试注册结果成功率（应该约85%）
        registration_results = [
            generator.generate_registration_result() for _ in range(100)
        ]
        reg_success_rate = sum(registration_results) / len(registration_results)
        assert (
            0.7 <= reg_success_rate <= 1.0
        ), f"注册成功率应该在合理范围内: {reg_success_rate}"
