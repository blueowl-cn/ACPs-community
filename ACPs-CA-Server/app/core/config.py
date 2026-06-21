"""
应用配置

使用 Pydantic V2 风格的配置管理，从环境变量中读取配置。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List


class Settings(BaseSettings):
    """应用配置类"""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    # 应用基础配置
    app_name: str = "Agent CA API"
    app_version: str = "1.0.0"
    debug: bool = True
    docs_enabled: bool = True

    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 8003

    # 数据库配置
    database_url: str = ""

    # 安全配置
    secret_key: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # 日志配置
    log_level: str = "DEBUG"
    log_file: str = "logs/app.log"

    # CORS 配置
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # CA 证书配置
    ca_cert_path: str = "certs/ca.crt"
    ca_key_path: str = "certs/ca.key"
    agent_cn_domain_suffix: str = "acps.pub"

    # ACME 配置
    acme_directory_url: str = "http://localhost:8003/acps-atr-v1/acme"
    acme_terms_of_service: str = "https://example.com/terms"
    acme_website: str = "https://agent-ca.example.com"
    acme_caa_identities: str = "agent-ca.example.com"

    # Mock 模式配置 (开发/测试环境)
    agent_registry_mock: bool = False
    http01_validation_mock: bool = False
    external_services_mock: bool = False  # 通用Mock开关

    # Agent 注册服务配置
    agent_registry_url: str = "http://localhost:8001"
    agent_registry_timeout: int = 10
    agent_registry_service_token: str = ""

    # SSO 服务配置
    sso_service_url: str = "http://localhost:8003"
    sso_service_timeout: int = 10

    # 外部服务重试配置
    external_service_max_retries: int = 3
    external_service_retry_delays: str = "1,2,4"  # 重试间隔（秒）

    # HTTP-01 验证配置
    http01_validation_timeout: int = 30
    http01_validation_retries: int = 2

    # ATR 管理功能 IP 限制配置
    atr_mgmt_allow_ip_list: str = "127.0.0.1,::1"

    @field_validator("cors_origins")
    @classmethod
    def parse_cors_origins(cls, v: str) -> List[str]:
        """解析 CORS 来源列表"""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @property
    def atr_mgmt_allow_ip_list_parsed(self) -> List[str]:
        """获取 ATR 管理功能允许的 IP 地址列表"""
        if isinstance(self.atr_mgmt_allow_ip_list, str):
            return [
                ip.strip()
                for ip in self.atr_mgmt_allow_ip_list.split(",")
                if ip.strip()
            ]
        return (
            self.atr_mgmt_allow_ip_list
            if isinstance(self.atr_mgmt_allow_ip_list, list)
            else []
        )

    @property
    def acme_caa_identities_list(self) -> List[str]:
        """获取 CAA 身份列表"""
        if isinstance(self.acme_caa_identities, str):
            return [
                identity.strip()
                for identity in self.acme_caa_identities.split(",")
                if identity.strip()
            ]
        return (
            self.acme_caa_identities
            if isinstance(self.acme_caa_identities, list)
            else [self.acme_caa_identities]
        )

    @property
    def external_service_retry_delays_list(self) -> List[int]:
        """获取外部服务重试延迟列表"""
        if isinstance(self.external_service_retry_delays, str):
            return [
                int(delay.strip())
                for delay in self.external_service_retry_delays.split(",")
                if delay.strip().isdigit()
            ]
        return [1, 2, 4]  # 默认值

    @property
    def agent_cn_domain_suffix_normalized(self) -> str:
        """获取标准化的 Agent CN 域名后缀"""
        suffix = (self.agent_cn_domain_suffix or "").strip()
        if suffix.startswith("."):
            suffix = suffix[1:]
        return suffix

    def build_agent_common_name(self, agent_id: str) -> str:
        """构造 Agent 证书的完整 CN"""
        suffix = self.agent_cn_domain_suffix_normalized
        if suffix:
            return f"{agent_id}.{suffix}"
        return agent_id

    @property
    def database_url_computed(self) -> str:
        """计算数据库连接 URL"""
        url = (self.database_url or "").strip()
        if not url:
            raise ValueError("DATABASE_URL environment variable is not configured.")
        return url


# 创建全局配置实例
settings = Settings()


def get_settings() -> Settings:
    """获取应用配置实例"""
    return settings


def get_db_url() -> str:
    """获取数据库连接 URL，用于 Alembic 等工具"""
    return settings.database_url_computed
