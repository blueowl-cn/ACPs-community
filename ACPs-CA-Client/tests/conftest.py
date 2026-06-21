"""
全局共享 fixtures，供所有层级测试使用。
"""

import os
import tempfile
import shutil

import pytest


@pytest.fixture
def tmp_workspace(tmp_path):
    """创建一个临时工作空间，包含标准子目录结构。"""
    dirs = {
        "private": tmp_path / "private",
        "certs": tmp_path / "certs",
        "csr": tmp_path / "csr",
    }
    for d in dirs.values():
        d.mkdir()
    return tmp_path


@pytest.fixture
def sample_aic():
    """返回一个合法的测试用 AIC。"""
    return "1.2.156.3088.1.TEST.AAAAAA.BBBBBB.1.ZZZZ"


@pytest.fixture
def config_file(tmp_workspace):
    """在临时工作空间中生成一份有效的配置文件，返回路径。"""
    conf_path = tmp_workspace / ".ca-client.conf"
    conf_path.write_text(
        f"CA_SERVER_BASE_URL = http://localhost:8003/acps-atr-v2\n"
        f"CHALLENGE_SERVER_BASE_URL = http://localhost:8004/acps-atr-v2\n"
        f"ACCOUNT_KEY_PATH = {tmp_workspace / 'private' / 'account.key'}\n"
        f"CERTS_DIR = {tmp_workspace / 'certs'}\n"
        f"PRIVATE_KEYS_DIR = {tmp_workspace / 'private'}\n"
        f"CSR_DIR = {tmp_workspace / 'csr'}\n"
        f"TRUST_BUNDLE_PATH = {tmp_workspace / 'certs' / 'trust-bundle.pem'}\n"
        f"CHALLENGE_DEPLOY_MOCK = true\n"
    )
    return str(conf_path)
