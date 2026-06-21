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
from app.core.config import settings

# Import database initialization
from app.core.db_session import create_db_and_tables

# Import ACME router and error handler
from app.acme.api import router as acme_router
from app.acme.error_handler import ACMEErrorHandler

# Import ATR management IP filter middleware
from app.core.atr_ip_filter import ATRManagementIPFilterMiddleware

# Import certificate management router
from app.certificates.api import router as certificates_router

# Import extension API router
from app.certificates.api_ext import router as ext_router

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
    title=settings.app_name,
    version=settings.app_version,
    description="Agent CA 认证系统后端 API",
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    lifespan=lifespan,
)

# 添加 ACME 错误处理中间件
app.add_middleware(ACMEErrorHandler)

# 添加 ATR 管理功能 IP 过滤中间件
app.add_middleware(ATRManagementIPFilterMiddleware)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 ACME 路由
app.include_router(acme_router, prefix="/acps-atr-v2/acme", tags=["ACME"])

# 注册证书管理路由
app.include_router(
    certificates_router,
    prefix="/admin/certificates",
    tags=["不在ACPs体系中的证书管理，基本的功能"],
)

# 注册扩展 API 路由 (Trust Bundle & Revoke Notify)
app.include_router(
    ext_router,
    prefix="/acps-atr-v2/ca",
    tags=["Extension API"],
)

# 注册CRL路由
app.include_router(crl_router, prefix="/acps-atr-v2/crl", tags=["CRL"])

# 注册OCSP路由
app.include_router(ocsp_router, prefix="/acps-atr-v2/ocsp", tags=["OCSP"])


# 健康检查端点
@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "service": "Agent CA API",
        "version": settings.app_version,
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
    # 启动服务器
    uvicorn.run(
        "main:app",
        host=settings.uvicorn_host,
        port=settings.uvicorn_port,
        reload=settings.uvicorn_reload,
        log_level=settings.uvicorn_log_level,
    )
