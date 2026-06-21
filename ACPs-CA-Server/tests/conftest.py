import os
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from app.core.db_session import engine
from tests.test_data_setup import cleanup_test_data


@pytest.fixture(scope="session", autouse=True)
def disable_mock_mode():
    """确保测试时禁用Mock模式"""
    # 强制设置环境变量为false
    mock_env_vars = [
        "AGENT_REGISTRY_MOCK",
        "HTTP01_VALIDATION_MOCK",
        "EXTERNAL_SERVICES_MOCK",
    ]

    for var in mock_env_vars:
        os.environ[var] = "false"

    yield


@pytest.fixture(scope="module")
def client():
    # 在导入app之前确保Mock被禁用
    from main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="function", autouse=True)
def clean_db():
    """为每个测试函数提供干净的数据库环境 - 自动应用到所有测试"""
    # 测试前清理
    with Session(engine) as session:
        cleanup_test_data(session)

    yield

    # 测试后清理
    with Session(engine) as session:
        cleanup_test_data(session)


@pytest.fixture
def db_session():
    """提供数据库会话"""
    with Session(engine) as session:
        yield session
