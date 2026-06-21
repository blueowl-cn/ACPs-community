"""
Agent CA 认证服务 - 应用入口点

这是基于 FastAPI 开发的 Agent CA 认证系统的主入口文件。
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
from dotenv import load_dotenv

# Import database initialization
from app.core.db_session import create_db_and_tables

# Import ACME router and error handler
from app.acme.api import router as acme_router
from app.acme.error_handler import ACMEErrorHandler

# Import ATR management IP filter middleware
from app.core.atr_ip_filter import ATRManagementIPFilterMiddleware

# Import certificate management router
from app.certificates.api import router as certificates_router

# Import certificate revoke router
from app.certificates.api_revoke import router as certificates_revoke_router

# Import CRL router
from app.crl.api import router as crl_router

# Import OCSP router
from app.ocsp.api import router as ocsp_router

# 加载环境变量
load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化数据库
    create_db_and_tables()
    yield
    # 关闭时的清理工作（如果需要）


# 创建 FastAPI 应用实例
app = FastAPI(
    title=os.getenv("APP_NAME", "Agent CA API"),
    version=os.getenv("APP_VERSION", "1.0.0"),
    description="Agent CA 认证系统后端 API",
    docs_url="/docs" if os.getenv("DOCS_ENABLED", "true").lower() == "true" else None,
    redoc_url="/redoc" if os.getenv("DOCS_ENABLED", "true").lower() == "true" else None,
    lifespan=lifespan,
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境可以使用 "*"，生产环境请指定具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加 ACME 错误处理中间件
app.add_middleware(ACMEErrorHandler)

# 添加 ATR 管理功能 IP 过滤中间件
app.add_middleware(ATRManagementIPFilterMiddleware)

# 注册 ACME 路由
app.include_router(acme_router, prefix="/acps-atr-v1/acme", tags=["ACME"])

# 注册证书管理路由
app.include_router(
    certificates_router,
    prefix="/admin/certificates",
    tags=["不在ACPs体系中的证书管理，基本的功能"],
)

# 注册证书吊销路由
app.include_router(
    certificates_revoke_router,
    prefix="/acps-atr-v1/mgmt",
    tags=["用于ACPs协议体系中的管理功能，暂时只有证书吊销"],
)

# 注册CRL路由
app.include_router(crl_router, prefix="/acps-atr-v1/crl", tags=["CRL"])

# 注册OCSP路由
app.include_router(ocsp_router, prefix="/acps-atr-v1/ocsp", tags=["OCSP"])


# 健康检查端点
@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "service": "Agent CA API",
        "version": os.getenv("APP_VERSION", "1.0.0"),
        "environment": os.getenv("APP_ENV", "development"),
    }


# 根路径
@app.get("/")
async def root():
    """根路径欢迎信息"""
    return {
        "message": "欢迎使用 Agent CA 认证服务 API",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
    }


# 当直接运行此文件时启动服务器
if __name__ == "__main__":
    # 从环境变量获取配置
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8003))
    debug = os.getenv("DEBUG", "true").lower() == "true"

    # 启动服务器
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=debug,  # 开发模式启用热重载
        log_level="debug" if debug else "info",
    )
