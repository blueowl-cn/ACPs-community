"""
HTTP-01 挑战验证服务

实现 ACME HTTP-01 挑战的验证逻辑，针对 Agent 服务进行特殊处理
"""

import httpx
import asyncio
from typing import Optional, Dict, Any
from dataclasses import dataclass
from app.core.config import get_settings
from .agent_registry import AgentInfo
from .mock_data import MockDataGenerator


@dataclass
class ValidationResult:
    """验证结果"""

    success: bool
    error: Optional[str] = None
    response_time: Optional[float] = None
    details: Optional[Dict[str, Any]] = None


class HTTP01ValidationService:
    """HTTP-01 验证服务"""

    def __init__(self):
        self.settings = get_settings()
        self.timeout = self.settings.http01_validation_timeout
        self.max_retries = self.settings.http01_validation_retries
        self.retry_delays = self.settings.external_service_retry_delays_list

        # Mock 模式支持
        self.is_mock_enabled = self.settings.http01_validation_mock
        if self.is_mock_enabled:
            self.mock_generator = MockDataGenerator()
            print("HTTP01ValidationService: Mock mode enabled")

    async def validate_challenge(
        self, agent_info: AgentInfo, token: str, key_authorization: str
    ) -> ValidationResult:
        """验证 HTTP-01 挑战

        Args:
            agent_info: Agent 信息
            token: 挑战令牌
            key_authorization: 密钥授权字符串

        Returns:
            ValidationResult: 验证结果
        """
        # Mock 模式
        if self.is_mock_enabled:
            print(
                f"HTTP01ValidationService: Using mock validation for agent: {agent_info.aic}, token: {token}"
            )
            mock_result = self.mock_generator.generate_http01_validation_result(
                agent_info.aic, token, key_authorization
            )
            # 将Mock结果转换为ValidationResult对象
            return ValidationResult(
                success=mock_result["success"],
                error=mock_result.get("error"),
                response_time=mock_result.get("response_time"),
                details=mock_result.get("details"),
            )

        # 真实模式
        try:
            # 构造验证URL - 使用Agent特定的路径
            challenge_url = self._build_challenge_url(agent_info, token)
            print(
                f"HTTP01ValidationService: Validating challenge for agent: {agent_info.aic}, URL: {challenge_url}"
            )
            # 执行验证请求
            result = await self._perform_validation_request(
                challenge_url, key_authorization
            )

            return result

        except Exception as e:
            return ValidationResult(success=False, error=f"Validation failed: {str(e)}")

    def _build_challenge_url(self, agent_info: AgentInfo, token: str) -> str:
        """构造挑战验证URL"""
        # 使用AgentInfo中的新方法构造URL：ca-challenge-url/{aic}/{token}
        return agent_info.get_challenge_url(token)

    async def _perform_validation_request(
        self, challenge_url: str, expected_content: str
    ) -> ValidationResult:
        """执行验证请求"""
        import time

        start_time = time.time()

        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout, follow_redirects=True
                ) as client:
                    response = await client.get(challenge_url)

                    response_time = time.time() - start_time

                    # 检查HTTP状态码
                    if response.status_code != 200:
                        error_msg = (
                            f"HTTP {response.status_code}: {response.reason_phrase}"
                        )
                        if attempt < self.max_retries:
                            last_error = error_msg
                            await self._wait_before_retry(attempt)
                            continue
                        else:
                            return ValidationResult(
                                success=False,
                                error=error_msg,
                                response_time=response_time,
                                details={
                                    "status_code": response.status_code,
                                    "url": challenge_url,
                                    "attempt": attempt + 1,
                                },
                            )

                    # 检查响应内容
                    content = response.text.strip()

                    if content == expected_content:
                        return ValidationResult(
                            success=True,
                            response_time=response_time,
                            details={
                                "status_code": response.status_code,
                                "url": challenge_url,
                                "attempt": attempt + 1,
                                "content_length": len(content),
                            },
                        )
                    else:
                        error_msg = f"Content mismatch. Expected: {expected_content[:50]}..., Got: {content[:50]}..."
                        if attempt < self.max_retries:
                            last_error = error_msg
                            await self._wait_before_retry(attempt)
                            continue
                        else:
                            return ValidationResult(
                                success=False,
                                error=error_msg,
                                response_time=response_time,
                                details={
                                    "status_code": response.status_code,
                                    "url": challenge_url,
                                    "attempt": attempt + 1,
                                    "expected_content": expected_content,
                                    "actual_content": content[:100],
                                },
                            )

            except httpx.TimeoutException:
                error_msg = f"Request timeout ({self.timeout}s)"
                last_error = error_msg
                if attempt < self.max_retries:
                    await self._wait_before_retry(attempt)
                    continue
                else:
                    return ValidationResult(
                        success=False,
                        error=error_msg,
                        response_time=time.time() - start_time,
                        details={
                            "url": challenge_url,
                            "attempt": attempt + 1,
                            "timeout": self.timeout,
                        },
                    )

            except httpx.RequestError as e:
                error_msg = f"Request error: {str(e)}"
                last_error = error_msg
                if attempt < self.max_retries:
                    await self._wait_before_retry(attempt)
                    continue
                else:
                    return ValidationResult(
                        success=False,
                        error=error_msg,
                        response_time=time.time() - start_time,
                        details={
                            "url": challenge_url,
                            "attempt": attempt + 1,
                            "error_type": type(e).__name__,
                        },
                    )

            except Exception as e:
                error_msg = f"Unexpected error: {str(e)}"
                return ValidationResult(
                    success=False,
                    error=error_msg,
                    response_time=time.time() - start_time,
                    details={
                        "url": challenge_url,
                        "attempt": attempt + 1,
                        "error_type": type(e).__name__,
                    },
                )

        # 不应该到这里，但以防万一
        return ValidationResult(
            success=False, error=last_error or "Unknown validation error"
        )

    async def _wait_before_retry(self, attempt: int):
        """重试前等待"""
        if attempt < len(self.retry_delays):
            delay = self.retry_delays[attempt]
        else:
            delay = self.retry_delays[-1]

        await asyncio.sleep(delay)

    async def pre_validate_agent_endpoint(
        self, agent_info: AgentInfo
    ) -> ValidationResult:
        """预验证Agent端点是否可访问（在创建挑战前）"""
        # Mock 模式
        if self.is_mock_enabled:
            print(
                f"HTTP01ValidationService: Using mock pre-validation for agent: {agent_info.aic}"
            )
            mock_result = self.mock_generator.generate_pre_validation_result(
                agent_info.aic
            )
            # 将Mock结果转换为ValidationResult对象
            return ValidationResult(
                success=mock_result["success"],
                error=mock_result.get("error"),
                details=mock_result.get("details"),
            )

        # 真实模式
        try:
            # 使用 x-caChallengeBaseUrl 作为健康检查端点基础
            base_url = agent_info.ca_challenge_base_url
            if not base_url:
                return ValidationResult(
                    success=False, error="No challenge URL available for agent"
                )

            # 构造健康检查URL - 使用同一主机的/status端点
            # 例如: http://localhost:8004/ca/agent -> http://localhost:8004/status
            from urllib.parse import urlparse

            parsed_url = urlparse(base_url)
            health_url = f"{parsed_url.scheme}://{parsed_url.netloc}/status"

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(health_url)

                if response.status_code != 200:
                    return ValidationResult(
                        success=False,
                        error=f"Agent health check failed: HTTP {response.status_code}",
                    )

                health_data = response.json()
                # 检查服务状态而不是agent_id匹配，因为Challenge Server是共享服务
                if health_data.get("status") != "running":
                    return ValidationResult(
                        success=False,
                        error=f"Agent service not running: {health_data.get('status')}",
                    )

                return ValidationResult(success=True)

        except Exception as e:
            return ValidationResult(
                success=False, error=f"Pre-validation failed: {str(e)}"
            )


# 全局验证服务实例
_validation_service: Optional[HTTP01ValidationService] = None


def get_http01_validation_service() -> HTTP01ValidationService:
    """获取 HTTP-01 验证服务实例"""
    global _validation_service
    if _validation_service is None:
        _validation_service = HTTP01ValidationService()
    return _validation_service
