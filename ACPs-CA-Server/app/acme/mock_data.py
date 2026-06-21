"""
Mock数据和工具类

为开发和测试环境提供模拟的外部服务数据
"""

import random
import secrets
import time
import string
from datetime import datetime, timedelta
from typing import Dict, Any, Optional


class MockDataGenerator:
    """Mock数据生成器"""

    # 预定义的组织名称池
    ORGANIZATIONS = [
        "TechCorp Solutions",
        "DataFlow Systems",
        "CloudEdge Innovations",
        "NeuralNet Dynamics",
        "QuantumByte Technologies",
        "AI Fusion Labs",
        "CyberSecure Networks",
        "SmartGrid Analytics",
        "RoboTech Industries",
        "BlockChain Ventures",
        "IoT Connected Ltd",
        "EdgeCompute Corp",
    ]

    # 预定义的部门名称池
    DEPARTMENTS = [
        "Engineering",
        "Research & Development",
        "AI Operations",
        "Data Science",
        "Security Division",
        "Infrastructure",
        "Platform Services",
        "DevOps",
        "Machine Learning",
        "Analytics",
    ]

    # 预定义的国家代码池
    COUNTRIES = ["US", "CA", "GB", "DE", "FR", "JP", "AU", "SG", "NL", "SE"]

    # 预定义的城市池
    CITIES = [
        "New York",
        "London",
        "Tokyo",
        "San Francisco",
        "Berlin",
        "Toronto",
        "Sydney",
        "Singapore",
        "Amsterdam",
        "Stockholm",
    ]

    # 预定义的域名后缀
    DOMAIN_SUFFIXES = [".com", ".org", ".net", ".ai", ".tech", ".cloud"]

    # 预定义的状态池
    AGENT_STATUSES = ["active", "pending", "maintenance"]

    @classmethod
    def random_string(cls, length: int, chars: str = string.ascii_lowercase) -> str:
        """生成随机字符串"""
        return "".join(random.choice(chars) for _ in range(length))

    @classmethod
    def random_number_string(cls, length: int) -> str:
        """生成随机数字字符串"""
        return "".join(random.choice(string.digits) for _ in range(length))

    @classmethod
    def generate_email(cls, company: str) -> str:
        """生成公司邮箱"""
        domain = company.lower().replace(" ", "").replace("&", "and")
        domain = "".join(c for c in domain if c.isalnum())
        username = cls.random_string(random.randint(5, 10))
        return f"{username}@{domain}.com"

    @classmethod
    def generate_domain(cls) -> str:
        """生成域名"""
        prefix = cls.random_string(random.randint(6, 12))
        suffix = random.choice(cls.DOMAIN_SUFFIXES)
        return f"{prefix}{suffix}"

    @classmethod
    def generate_aic(cls) -> str:
        """
        生成随机的 AIC (Agent Identity Code)

        根据 ACPs-spec-AIC-v01.00 规范，AIC 由 32 位大写字母与数字组成
        """
        # 生成 32 位大写字母和数字的组合
        chars = string.ascii_uppercase + string.digits
        return "".join(random.choice(chars) for _ in range(32))

    @classmethod
    def generate_organization_info(cls) -> Dict[str, str]:
        """生成组织信息"""
        org_name = random.choice(cls.ORGANIZATIONS)
        return {
            "organizationName": org_name,
            "organizationalUnit": random.choice(cls.DEPARTMENTS),
            "country": random.choice(cls.COUNTRIES),
            "state": cls.random_string(2, string.ascii_uppercase),
            "locality": random.choice(cls.CITIES),
            "contactEmail": cls.generate_email(org_name),
        }

    @classmethod
    def generate_agent_info(cls, aic: str = None) -> Dict[str, Any]:
        """
        生成完整的 Agent 信息 - 符合 ACS 数据结构

        根据 ATR-DESIGN.md 2.3.1 章节的响应数据结构生成 mock 数据
        """
        if not aic:
            aic = cls.generate_aic()

        # 90%概率返回激活的Agent，10%概率返回非激活Agent
        is_active = random.random() > 0.1

        org_info = cls.generate_organization_info()

        # 生成 agent 名称和版本
        agent_name = (
            f"{random.choice(['Agent', 'Node', 'Client', 'Service'])}-{aic[-8:]}"
        )
        version = (
            f"{random.randint(1, 3)}.{random.randint(0, 9)}.{random.randint(0, 9)}"
        )

        # 生成挑战 URL
        domain = cls.generate_domain()
        ca_challenge_base_url = f"https://{domain}/ca/agent"

        # 生成能力和技能信息
        capabilities = {
            "communication": ["jsonrpc", "rest"],
            "security": ["mtls", "oauth2"],
            "protocols": ["acps-aip-v1"],
        }

        skills = [
            {"name": "data_processing", "version": "1.0"},
            {"name": "ml_inference", "version": "2.1"},
            {"name": "text_generation", "version": "1.5"},
        ]

        # 生成端点信息
        endpoints = [
            {
                "url": f"https://{domain}/acps-aip-v1/rpc",
                "security": [{"mtls": []}],
                "transport": "JSONRPC",
            }
        ]

        # 根据 ACS 格式构造完整的响应数据
        return {
            "aic": aic,
            "active": is_active,
            "name": agent_name,
            "version": version,
            "provider": {
                "organization": org_info["organizationName"],
                "department": org_info["organizationalUnit"],
                "countryCode": org_info["country"],
            },
            "securitySchemes": {
                "mtls": {
                    "description": "智能体间mTLS双向认证",
                    "type": "mutualTLS",
                    "x-caChallengeBaseUrl": ca_challenge_base_url,
                }
            },
            "endPoints": endpoints,
            "capabilities": capabilities,
            "skills": skills,
        }

    @classmethod
    def generate_http01_challenge_response(
        cls, expected_content: str
    ) -> Dict[str, Any]:
        """生成HTTP-01挑战响应"""
        # 80%概率返回正确内容，20%概率返回错误内容
        success_rate = 0.8

        if random.random() < success_rate:
            # 成功情况
            return {
                "status_code": 200,
                "content": expected_content,
                "response_time": random.uniform(0.1, 2.0),
                "headers": {
                    "content-type": "text/plain",
                    "server": f"Agent-Server/{random.randint(1, 5)}.{random.randint(0, 9)}.{random.randint(0, 9)}",
                    "x-agent-id": cls.generate_aic(),
                },
            }
        else:
            # 失败情况
            error_scenarios = [
                {
                    "status_code": 404,
                    "content": "Not Found",
                    "error": "Challenge token not found",
                },
                {
                    "status_code": 200,
                    "content": cls.random_string(
                        64, string.ascii_lowercase + string.digits
                    ),  # 错误的内容
                    "error": "Content mismatch",
                },
                {
                    "status_code": 500,
                    "content": "Internal Server Error",
                    "error": "Agent service error",
                },
                {
                    "status_code": 503,
                    "content": "Service Unavailable",
                    "error": "Agent temporarily unavailable",
                },
            ]

            scenario = random.choice(error_scenarios)
            scenario["response_time"] = random.uniform(5.0, 30.0)  # 错误情况响应较慢
            return scenario

    @classmethod
    def generate_agent_health_check(cls, agent_id: str) -> Dict[str, Any]:
        """生成Agent健康检查响应"""
        # 85%概率健康，15%概率不健康
        is_healthy = random.random() > 0.15

        if is_healthy:
            return {
                "status_code": 200,
                "data": {
                    "agent_id": agent_id,
                    "status": "healthy",
                    "version": f"{random.randint(1, 5)}.{random.randint(0, 9)}.{random.randint(0, 9)}",
                    "uptime": random.randint(3600, 2592000),  # 1小时到30天
                    "last_heartbeat": datetime.utcnow().isoformat(),
                    "capabilities": ["acme-challenge", "certificate-management"],
                    "load": random.uniform(0.1, 0.8),
                },
            }
        else:
            error_responses = [
                {"status_code": 503, "error": "Agent overloaded"},
                {"status_code": 500, "error": "Internal agent error"},
                {"status_code": 404, "error": "Agent not found"},
            ]
            return random.choice(error_responses)

    # 以下方法供AgentRegistryClient和HTTP01ValidationService调用

    def generate_endpoint_validation_result(self) -> bool:
        """生成端点验证结果（80%成功率）"""
        return random.random() > 0.2

    def generate_registration_result(self) -> bool:
        """生成证书请求注册结果（85%成功率）"""
        return random.random() > 0.15

    def generate_notification_result(self) -> bool:
        """生成证书签发通知结果（90%成功率）"""
        return random.random() > 0.1

    def generate_ownership_verification_result(self) -> bool:
        """生成所有权验证结果（75%成功率）"""
        return random.random() > 0.25

    def generate_http01_validation_result(
        self, aic: str, token: str, key_authorization: str
    ):
        """生成HTTP-01验证结果"""
        # 需要导入ValidationResult，为了避免循环导入，这里返回字典
        success = random.random() > 0.2  # 80%成功率

        if success:
            return {
                "success": True,
                "response_time": random.uniform(0.5, 3.0),
                "details": {
                    "status_code": 200,
                    "url": f"https://mock-agent-{aic[:8]}.example.com/ca/agent/challenge/{aic}/{token}",
                    "attempt": 1,
                    "content_length": len(key_authorization),
                },
            }
        else:
            error_scenarios = [
                "HTTP 404: Token not found",
                "HTTP 500: Agent service error",
                "HTTP 503: Agent temporarily unavailable",
                "Content mismatch",
                "Request timeout (10.0s)",
            ]
            return {
                "success": False,
                "error": random.choice(error_scenarios),
                "response_time": random.uniform(5.0, 30.0),
                "details": {
                    "status_code": random.choice([404, 500, 503]),
                    "url": f"https://mock-agent-{aic[:8]}.example.com/ca/agent/challenge/{aic}/{token}",
                    "attempt": random.randint(1, 3),
                },
            }

    def generate_pre_validation_result(self, aic: str):
        """生成预验证结果"""
        success = random.random() > 0.15  # 85%成功率

        if success:
            return {"success": True, "details": {"agent_id": aic, "status": "healthy"}}
        else:
            error_scenarios = [
                "Agent health check failed: HTTP 503",
                "Agent ID mismatch in health check",
                "Pre-validation failed: Connection timeout",
            ]
            return {"success": False, "error": random.choice(error_scenarios)}


class MockDelaySimulator:
    """网络延迟模拟器"""

    @staticmethod
    def simulate_network_delay():
        """模拟网络延迟"""
        # 模拟不同的网络条件
        delay_scenarios = [
            (0.1, 0.3, 0.7),  # 本地网络 (70%概率)
            (0.5, 1.5, 0.2),  # 一般网络 (20%概率)
            (2.0, 5.0, 0.08),  # 慢网络 (8%概率)
            (10.0, 30.0, 0.02),  # 超慢网络 (2%概率)
        ]

        for min_delay, max_delay, probability in delay_scenarios:
            if random.random() < probability:
                delay = random.uniform(min_delay, max_delay)
                time.sleep(delay)
                return delay

        # 默认延迟
        delay = random.uniform(0.1, 0.3)
        time.sleep(delay)
        return delay


class MockCacheSimulator:
    """缓存模拟器，模拟真实的缓存行为"""

    def __init__(self, ttl_seconds: int = 300):
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.ttl = ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        if key in self.cache:
            entry = self.cache[key]
            if time.time() - entry["timestamp"] < self.ttl:
                # 模拟缓存命中的快速响应
                time.sleep(random.uniform(0.001, 0.01))
                return entry["data"]
            else:
                # 缓存过期
                del self.cache[key]
        return None

    def set(self, key: str, value: Any):
        """设置缓存值"""
        self.cache[key] = {"data": value, "timestamp": time.time()}

    def invalidate(self, key: str):
        """使缓存失效"""
        if key in self.cache:
            del self.cache[key]


# 全局缓存实例
mock_cache = MockCacheSimulator()


def generate_realistic_error(service_name: str, operation: str) -> Dict[str, Any]:
    """生成真实的错误场景"""
    error_scenarios = {
        "agent_registry": [
            {"code": "RATE_LIMITED", "message": "Too many requests", "retry_after": 60},
            {
                "code": "SERVICE_UNAVAILABLE",
                "message": "Registry service under maintenance",
            },
            {"code": "AUTHENTICATION_FAILED", "message": "Invalid service token"},
            {"code": "AGENT_NOT_FOUND", "message": "Agent not found in registry"},
            {
                "code": "DATABASE_ERROR",
                "message": "Registry database connection failed",
            },
        ],
        "http01_validation": [
            {"code": "CONNECTION_TIMEOUT", "message": "Agent endpoint not reachable"},
            {"code": "SSL_ERROR", "message": "SSL certificate verification failed"},
            {"code": "DNS_RESOLUTION", "message": "Cannot resolve agent hostname"},
            {"code": "FIREWALL_BLOCKED", "message": "Connection blocked by firewall"},
            {"code": "AGENT_OFFLINE", "message": "Agent service is offline"},
        ],
    }

    scenarios = error_scenarios.get(service_name, [])
    if scenarios:
        error = random.choice(scenarios)
        error["service"] = service_name
        error["operation"] = operation
        error["timestamp"] = datetime.utcnow().isoformat()
        error["correlation_id"] = secrets.token_hex(8)
        return error

    return {
        "code": "UNKNOWN_ERROR",
        "message": f"Unknown error in {service_name}",
        "service": service_name,
        "operation": operation,
    }
