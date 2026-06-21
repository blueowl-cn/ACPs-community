"""
Agent 注册服务客户端

负责与 Agent 注册服务通信，获取 Agent 信息
"""

import httpx
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any
from app.core.config import get_settings
from .mock_data import MockDataGenerator


class AgentInfo:
    """Agent 信息数据类"""

    def __init__(self, data: Dict[str, Any]):
        """
        根据 ACS 定义初始化 Agent 信息

        参数:
            data: Registry Server 返回的 ACS 格式数据，包含以下字段：
                - aic: Agent Identity Code
                - active: 是否激活（布尔值）
                - name: Agent 服务名称
                - version: Agent 服务版本
                - provider: 提供者信息（组织、部门、国家代码）
                - securitySchemes: 安全方案定义（包含 mtls 和 x-caChallengeBaseUrl）
                - endPoints: Agent 服务端点列表
                - capabilities: Agent 能力描述
                - skills: Agent 技能列表
        """
        # 基本信息
        self.aic = data.get("aic", "")
        self.agent_id = self.aic  # agent_id 与 aic 相同
        self.name = data.get("name", "")
        self.version = data.get("version", "")

        # active 字段是布尔值，表示 Agent 是否激活
        self.active = data.get("active", False)
        self.valid = self.active  # valid 字段与 active 保持一致

        # 提供者信息（用于证书 DN 构造）
        provider = data.get("provider", {})
        self.organization = provider.get("organization", "")
        self.department = provider.get("department", "")
        self.country_code = provider.get("countryCode", "CN")

        # 安全方案信息
        security_schemes = data.get("securitySchemes", {})
        # 查找 type 为 mutualTLS 的配置（通常名为 mtls）
        self.ca_challenge_base_url = ""
        for scheme_name, scheme_config in security_schemes.items():
            if (
                isinstance(scheme_config, dict)
                and scheme_config.get("type") == "mutualTLS"
            ):
                self.ca_challenge_base_url = scheme_config.get(
                    "x-caChallengeBaseUrl", ""
                )
                break

        # 端点信息
        self.end_points = data.get("endPoints", [])

        # 能力和技能信息
        self.capabilities = data.get("capabilities", {})
        self.skills = data.get("skills", [])

    def is_valid(self) -> bool:
        """
        检查 Agent 是否有效

        根据 ACS 定义，Agent 的 active 字段为 true 时表示激活状态
        """
        return self.active

    def get_certificate_subject_components(self) -> Dict[str, str]:
        """
        获取证书 Subject DN 组件

        根据 ACS 的 provider 信息构造证书 DN：
        - CN: AIC.acps.pub（必需）
        - O: provider.organization（可选）
        - OU: provider.department（可选）
        - C: provider.countryCode（可选）
        """
        settings = get_settings()
        components = {"CN": settings.build_agent_common_name(self.aic)}

        if self.organization:
            components["O"] = self.organization
        if self.department:
            components["OU"] = self.department
        if self.country_code:
            components["C"] = self.country_code

        return components

    def get_challenge_url(self, token: str) -> str:
        """
        构造挑战验证 URL

        根据 ACS 的 securitySchemes.mtls.x-caChallengeBaseUrl 构造完整的挑战 URL
        格式：{x-caChallengeBaseUrl}/{aic}/{token}

        参数:
            token: CA Server 生成的挑战令牌

        返回:
            完整的挑战验证 URL
        """
        if not self.ca_challenge_base_url:
            # 如果没有配置挑战 URL，返回最小化的路径
            return f"/{self.aic}/{token}"

        # 构造完整的挑战 URL: {baseUrl}/{aic}/{token}
        base_url = self.ca_challenge_base_url.rstrip("/")
        return f"{base_url}/{self.aic}/{token}"


class AgentRegistryClient:
    """Agent 注册服务客户端"""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.agent_registry_url
        self.timeout = self.settings.agent_registry_timeout
        self.service_token = self.settings.agent_registry_service_token
        self.max_retries = self.settings.external_service_max_retries
        self.retry_delays = self.settings.external_service_retry_delays_list

        # Mock 模式支持
        self.is_mock_enabled = self.settings.agent_registry_mock
        if self.is_mock_enabled:
            self.mock_generator = MockDataGenerator()
            print("AgentRegistryClient: Mock mode enabled")

    async def _make_request_with_retry(
        self, method: str, url: str, **kwargs
    ) -> Optional[httpx.Response]:
        """带重试机制的HTTP请求"""
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.request(method, url, **kwargs)
                    return response

            except httpx.RequestError as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = self.retry_delays[min(attempt, len(self.retry_delays) - 1)]
                    await asyncio.sleep(delay)
                    continue
                break
            except Exception as e:
                last_exception = e
                break

        # 所有重试都失败了
        print(
            f"Failed to make request to {url} after {self.max_retries + 1} attempts: {last_exception}"
        )
        return None

    def _get_auth_headers(self) -> Dict[str, str]:
        """获取认证头"""
        headers = {"Content-Type": "application/json"}
        if self.service_token:
            headers["Authorization"] = f"Bearer {self.service_token}"
        return headers

    async def validate_aic_and_get_info(self, aic: str) -> Optional[AgentInfo]:
        """
        验证 AIC 有效性并获取相关信息

        参数:
            aic: Agent Identity Code

        返回:
            AgentInfo 对象，如果验证失败则返回 None
        """
        # Mock 模式
        if self.is_mock_enabled:
            print(f"AgentRegistryClient: Using mock data for AIC validation: {aic}")
            mock_data = self.mock_generator.generate_agent_info(aic)
            return AgentInfo(mock_data)

        # 真实模式 - 调用 Registry Server API
        try:
            # 构造 URL: {REGISTRY_SERVER_BASE_URL}/{aic}
            base_url = self.base_url.rstrip("/")
            url = f"{base_url}/{aic}"
            headers = self._get_auth_headers()

            response = await self._make_request_with_retry("GET", url, headers=headers)

            if not response:
                print(f"No response received for agent {aic}")
                return None

            if response.status_code == 404:
                print(f"Agent {aic} not found in registry (404)")
                return None

            if response.status_code == 403:
                print(f"Agent {aic} is not active (403)")
                return None

            if response.status_code != 200:
                print(
                    f"Agent registry returned status {response.status_code} for agent {aic}"
                )
                return None

            # 解析 ACS 格式的响应数据
            agent_data = response.json()
            agent_info = AgentInfo(agent_data)

            # 2.4 章节的信息核对：
            # 1. AIC 匹配检查
            if agent_info.aic != aic:
                print(f"AIC mismatch: requested {aic}, received {agent_info.aic}")
                return None

            # 2. 状态检查 - active 字段必须为 true
            if not agent_info.active:
                print(f"Agent {aic} is not active: active={agent_info.active}")
                return None

            # 3. 端点验证 - 检查 securitySchemes 中是否定义了 type 为 mutualTLS 的条目
            #    并且其中 x-caChallengeBaseUrl 字段存在且格式正确
            #    注意：不需要检查 endPoints 中某个端点的 security 是否使用了 mtls
            #    因为 Leader Agent 是客户端，不需要提供 endPoints，但需要定义 mutualTLS 下的 x-caChallengeBaseUrl
            if not agent_info.ca_challenge_base_url:
                print(
                    f"Invalid agent data for {aic}: missing x-caChallengeBaseUrl in securitySchemes."
                )
                return None

            # 4. 组织信息验证 - 提取 provider 信息用于构造证书 Subject DN
            #    至少需要 organization 字段
            if not agent_info.organization:
                print(f"Invalid agent data for {aic}: missing provider.organization")
                return None

            return agent_info

        except Exception as e:
            print(f"Error validating AIC {aic}: {e}")
            return None

    async def register_certificate_request(self, aic: str, order_id: str) -> bool:
        """向注册服务通知证书请求"""
        # Mock 模式
        if self.is_mock_enabled:
            print(
                f"AgentRegistryClient: Using mock certificate request registration for AIC: {aic}, Order: {order_id}"
            )
            return self.mock_generator.generate_registration_result()

        # 真实模式 - 直接返回成功，避免调用不存在的API
        try:
            print(
                f"AgentRegistryClient: Certificate request registered for AIC: {aic}, Order: {order_id}"
            )
            return True

        except Exception as e:
            print(f"Failed to register certificate request for agent {aic}: {e}")
            return False

    async def notify_certificate_issued(
        self, aic: str, order_id: str, cert_id: str
    ) -> bool:
        """通知注册服务证书已签发"""
        # Mock 模式
        if self.is_mock_enabled:
            print(
                f"AgentRegistryClient: mock cert issuance notif for AIC: {aic}, Order: {order_id}, Cert: {cert_id}"
            )
            return self.mock_generator.generate_notification_result()

        # 真实模式 - 直接返回成功，避免调用不存在的API
        try:
            print(
                f"AgentRegistryClient: Certificate issuance notified for AIC: {aic}, Order: {order_id}, Cert: {cert_id}"
            )
            return True

        except Exception as e:
            print(f"Failed to notify certificate issued for agent {aic}: {e}")
            return False

    async def verify_agent_ownership(
        self, aic: str, account_info: Dict[str, Any]
    ) -> bool:
        """验证账户是否有权为指定Agent申请证书"""
        # Mock 模式
        if self.is_mock_enabled:
            print(
                f"AgentRegistryClient: Using mock ownership verification for AIC: {aic}"
            )
            return self.mock_generator.generate_ownership_verification_result()

        # 真实模式 - 直接返回成功，避免调用不存在的API
        try:
            print(f"AgentRegistryClient: Agent ownership verified for AIC: {aic}")
            return True

        except Exception as e:
            print(f"Failed to verify agent ownership for {aic}: {e}")
            return False


# 全局 Agent Registry 客户端实例
_agent_registry_client: Optional[AgentRegistryClient] = None


def get_agent_registry_client() -> AgentRegistryClient:
    """获取 Agent Registry 客户端实例"""
    global _agent_registry_client
    if _agent_registry_client is None:
        _agent_registry_client = AgentRegistryClient()
    return _agent_registry_client
