import uvicorn
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.discovery.exception import ADPException 
from acps_sdk.adp import ErrorDetail, DiscoveryResponse
from app.core.config import settings
from app.core.base_exception import BaseException as AppBaseException
from app.core.database import create_db_and_tables, close_db
from app.core.utils import ColoredFormatter
from app.sync.client import start_drc_sync, stop_drc_sync
from app.discovery.discovery_api import router as discovery_router
from app.sync.api import router as drc_router
from app.discovery.discovery_api import start_health_check_task, stop_health_check_task


# 配置 logging
handler = logging.StreamHandler()
handler.setFormatter(
    ColoredFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)

logging.basicConfig(
    level=settings.APP_LOG_LEVEL.upper(),
    handlers=[handler],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理器。"""
    try:
        # 创建数据库表
        await create_db_and_tables()
        logger.info("数据库表初始化成功")
    except Exception as e:
        logger.error(f"数据库表初始化失败: {e}")

    try:
        # 启动 DRC 同步服务
        await start_drc_sync()
        logger.info("DRC 同步服务启动成功")
        logger.info("开始监控Registry数据变化...")
    except Exception as e:
        logger.error(f"DRC 同步服务启动失败: {e}")

    try:
        await start_health_check_task()
        logger.info("转发服务器健康检查任务启动成功")
    except Exception as e:
        logger.error(f"转发服务器健康检查任务启动失败: {e}")


    yield

    # 关闭：停止 DRC 同步服务和关闭数据库连接
    try:
        await stop_drc_sync()
        logger.info("DRC 同步服务停止成功")
    except Exception as e:
        logger.error(f"DRC 同步服务停止失败: {e}")

    try:
        await close_db()
        logger.info("数据库连接关闭成功")
    except Exception as e:
        logger.error(f"数据库连接关闭失败: {e}")


app = FastAPI(
    title=settings.APP_NAME,
    description=settings.APP_DESC,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    root_path=settings.APP_ROOT_PATH,
    lifespan=lifespan,
)

@app.exception_handler(ADPException)
async def adp_exception_handler(request: Request, exc: ADPException):
    logger.error("ADPException caught: %s", exc, exc_info=True)
    err: ErrorDetail = exc.error_data
    http_status = err.code // 100
    if http_status not in (307, 400, 401, 429, 500):
        http_status = 500
    error_response = DiscoveryResponse.failure(
        code=err.code,
        message=err.message,
        data=err.data,
    )
    return JSONResponse(status_code=http_status, content=error_response.to_dict())

@app.exception_handler(Exception)
async def universal_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception at %s %s", request.method, request.url)
    error_response = DiscoveryResponse.failure(
        code=50001,
        message="InternalError",
        data="An unexpected server error occurred.",
    )
    return JSONResponse(status_code=500, content=error_response.to_dict())

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 包含路由
app.include_router(
    discovery_router, prefix="/acps-adp-v2", tags=["用户使用的发现API"]
)
app.include_router(
    drc_router, prefix="/admin/drc", tags=["数据同步drc的管理维护测试用API"]
)


@app.get("/")
async def root():
    """root端点。"""
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "description": settings.APP_DESC,
    }


if __name__ == "__main__":
    logger.info("启动Discovery Server")
    logger.info(f"服务地址: http://{settings.UVICORN_HOST}:{settings.UVICORN_PORT}")
    logger.info(f"API文档: http://{settings.UVICORN_HOST}:{settings.UVICORN_PORT}/docs")
    logger.info(f"Registry DRC URL: {settings.DRC_BASE_URL}")
    logger.info(f"数据库: {settings.DATABASE_URL}")
    logger.info(f"自动重载: {'启用' if settings.UVICORN_RELOAD else '禁用'}")
    logger.info(f"日志级别: {settings.UVICORN_LOG_LEVEL}")

    uvicorn.run(
        "main:app",
        host=settings.UVICORN_HOST,
        port=settings.UVICORN_PORT,
        reload=settings.UVICORN_RELOAD,
        log_level=settings.UVICORN_LOG_LEVEL,
    )
