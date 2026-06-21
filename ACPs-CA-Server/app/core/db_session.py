"""
数据库会话管理

使用 SQLModel 和 SQLAlchemy 管理数据库连接和会话。
"""

from sqlmodel import SQLModel, create_engine, Session
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# 创建数据库引擎
engine = create_engine(
    settings.database_url_computed,
    echo=settings.debug,  # 开发环境下打印 SQL 语句
    pool_pre_ping=True,  # 连接前检查连接是否有效
    pool_recycle=3600,  # 连接回收时间（秒）
)


def create_db_and_tables():
    """创建数据库表"""
    try:
        SQLModel.metadata.create_all(engine)
        logger.info("数据库表创建成功")
    except Exception as e:
        logger.error(f"创建数据库表失败: {e}")
        raise


def get_session():
    """获取数据库会话"""
    with Session(engine) as session:
        yield session


def get_db():
    """FastAPI 依赖注入使用的数据库会话"""
    with Session(engine) as session:
        yield session
