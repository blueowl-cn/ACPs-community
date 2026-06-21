import os
import sys
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    UVICORN_HOST: str = "0.0.0.0"
    UVICORN_PORT: int = 8004
    UVICORN_RELOAD: bool = False
    CHALLENGE_DIR: Path = Path("./challenges")
    LOG_LEVEL: str = "INFO"
    BASE_URL: str = "/acps-atr-v2"

    class Config:
        # 默认为 .env，但允许通过 ENV_FILE 环境变量覆盖
        env_file = os.getenv("ENV_FILE", ".env")
        env_file_encoding = "utf-8"


# 强制要求配置文件存在
_env_path = Path(Settings.Config.env_file)
if not _env_path.is_file():
    print(f"CRITICAL: Configuration file '{_env_path}' not found in current directory. - config.py:24")
    print(
        "Tip: You can specify a custom configuration file using the ENV_FILE environment variable."
    )
    sys.exit(1)

settings = Settings()
