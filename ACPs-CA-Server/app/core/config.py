"""
应用配置

使用 Pydantic V2 风格的配置管理，从环境变量中读取配置。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    """应用配置类"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 应用基础配置
    app_name: str = "Agent CA API"
    app_version: str = "1.0.0"
    docs_enabled: bool = True

    # Uvicorn 服务器配置
    uvicorn_host: str = "0.0.0.0"
    uvicorn_port: int = 8003
    uvicorn_reload: bool = False
    uvicorn_log_level: str = "info"

    # 数据库配置
    database_url: str = ""

    # CA 证书配置
    ca_cert_path: str = "certs/ca.crt"
    ca_key_path: str = "certs/ca.key"
    agent_cn_domain_suffix: str = "acps.pub"

    # ACME 配置
    acme_directory_url: str = "http://localhost:8003/acps-atr-v2/acme"

    # Mock 模式配置 (开发/测试环境)
    agent_registry_mock: bool = False
    http01_validation_mock: bool = False

    # Agent 注册服务配置
    agent_registry_url: str = "http://localhost:8001"
    agent_registry_timeout: int = 10
    agent_registry_service_token: str = ""

    # 外部服务重试配置
    external_service_max_retries: int = 3
    external_service_retry_delays: str = "1,2,4"  # 重试间隔（秒）

    # HTTP-01 验证配置
    http01_validation_timeout: int = 30
    http01_validation_retries: int = 2

    # ATR 管理功能 IP 限制配置
    atr_mgmt_allow_ip_list: str = "127.0.0.1,::1"

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
