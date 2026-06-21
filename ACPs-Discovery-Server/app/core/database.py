"""
数据库配置与会话管理。

此模块为 Agent Discovery Server 提供 SQLModel/SQLAlchemy 的数据库引擎、
会话管理以及数据库工具函数。
"""

from typing import AsyncGenerator

from sqlmodel import SQLModel, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


# 为数据库操作创建异步引擎
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DATABASE_OUTPUT_SQL,
    future=True,
)

# Create async session factory
AsyncSessionLocal = sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    获取异步数据库会话的依赖（生成器）。

    Yields:
        AsyncSession: 异步数据库会话
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def create_db_and_tables():
    """在数据库中创建表（如果尚不存在）。"""
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def close_db():
    """关闭数据库连接。"""
    await async_engine.dispose()
