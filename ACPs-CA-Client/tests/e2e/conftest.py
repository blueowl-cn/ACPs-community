"""
E2E 层级的 conftest — 生成指向临时工作空间的真实配置文件，
检测 ca-server 是否可用。
"""

import os
import pathlib

import pytest
import requests


CA_SERVER_URL = "http://localhost:8003/acps-atr-v2"


def _ca_server_is_reachable():
    """检测 ca-server 是否在线。"""
    try:
        resp = requests.get(f"{CA_SERVER_URL}/acme/directory", timeout=3)
        return resp.ok
    except Exception:
        return False


@pytest.fixture(scope="session", autouse=True)
def check_ca_server():
    """Session 级 fixture：若 ca-server 不可达则跳过整个 E2E 套件。"""
    if not _ca_server_is_reachable():
        pytest.skip(
            "ca-server is not reachable at "
            f"{CA_SERVER_URL}. Start it with AGENT_REGISTRY_MOCK=true "
            "HTTP01_VALIDATION_MOCK=true before running E2E tests."
        )


@pytest.fixture
def e2e_config(tmp_path):
    """
    基于 e2e.conf 模板生成一份临时配置文件，
    将 {workspace} 替换为 tmp_path。
    """
    template = pathlib.Path(__file__).parent / "e2e.conf"
    content = template.read_text().replace("{workspace}", str(tmp_path))

    # 确保子目录存在
    for sub in ("private", "certs", "csr"):
        (tmp_path / sub).mkdir(exist_ok=True)

    conf_path = tmp_path / ".ca-client.conf"
    conf_path.write_text(content)
    return str(conf_path)


@pytest.fixture
def e2e_aic():
    """返回 E2E 测试用 AIC。"""
    return "1.2.156.3088.0001.00001.E2EAAA.E2EBBB.1.0TST"
