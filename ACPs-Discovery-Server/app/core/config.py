"""
Agent Discovery Server 的配置管理。

此模块通过 Pydantic Settings 从环境变量和 .env 文件加载配置。
"""

import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量和 .env 文件加载的应用配置。"""

    # Basic app settings
    APP_NAME: str = Field(default="Agent Discovery Server")
    APP_VERSION: str = Field(default="1.0.0")
    APP_DESC: str = Field(default="Agent 发现 API")
    APP_LOG_LEVEL: str = Field(default="info")
    APP_ROOT_PATH: str = Field(default="")

    # Server settings
    UVICORN_HOST: str = Field(default="0.0.0.0")
    UVICORN_PORT: int = Field(default=8005)
    UVICORN_RELOAD: bool = Field(default=False)
    UVICORN_LOG_LEVEL: str = Field(default="info")

    # 数据库配置
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "asyncpg://user:pass@localhost:5432/discovery",
    )
    DATABASE_OUTPUT_SQL: bool = Field(default=False)

    # DASHSCOPE API key
    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")

    # Embedding 服务配置
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL")
    EMBEDDING_MODEL_NAME: str = os.getenv(
        "EMBEDDING_MODEL_NAME", "text-embedding-3-small"
    )

    # 业务配置（与 DRC 注册中心相关）
    DRC_BASE_URL: str = Field(default="http://localhost:8001")
    DRC_CHANGES_PULL_INTERVAL: int = Field(default=30)
    DRC_SNAPSHOT_CHUNK_SIZE: int = Field(default=10000)
    DRC_CHANGES_CHUNK_SIZE: int = Field(default=1000)

    # DRC Webhook配置
    DRC_WEBHOOK_SECRET: str = Field(default="test_123")
    DRC_WEBHOOK_RECEIVE_URL: str = Field(
        default="http://localhost:8005/admin/drc/webhooks/receive"
    )

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )


# 创建全局的 settings 实例（模块级别）
settings = Settings()


def get_settings() -> Settings:
    """获取全局的 settings 实例。"""
    return settings
