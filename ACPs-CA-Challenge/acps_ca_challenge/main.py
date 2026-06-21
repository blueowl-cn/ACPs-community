#!/usr/bin/env python3
"""
Agent Trusted Registration (ATR) 挑战服务器。

实现了 Agent Trusted Registration 协议中的挑战服务器规范。
参考文档: ATR-CA-Challenge.md

本服务器主要负责：
1. 接收来自 CA 客户端 (Agent) 的挑战响应。
2. 向 CA 服务器提供挑战响应以进行验证。
"""
import logging
import sys
from fastapi import FastAPI
from acps_ca_challenge.api import router
from acps_ca_challenge.api_status import router_status
from acps_ca_challenge.config import settings
from acps_ca_challenge.service import init_storage

# 配置日志
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="[%(levelname)s] %(asctime)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOGGER = logging.getLogger("challenge_server")

# 初始化存储
try:
    init_storage()
    LOGGER.info(f"Challenge directory: {settings.CHALLENGE_DIR}")
except Exception as e:
    LOGGER.critical(f"Failed to initialize storage: {e}")
    sys.exit(1)

app = FastAPI(
    title="ATR Challenge Server",
    description="Agent Trusted Registration (ATR) Challenge Server",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

BASE_URL=settings.BASE_URL.rstrip("/") or "/"

app.include_router(router_status, prefix="")
app.include_router(router, prefix=BASE_URL)

def run():
    import uvicorn

    uvicorn.run(
        "acps_ca_challenge.main:app",
        host=settings.UVICORN_HOST,
        port=settings.UVICORN_PORT,
        reload=settings.UVICORN_RELOAD,
    )


if __name__ == "__main__":
    run()
