"""integration 层级的 conftest — 提供 Click CliRunner 和 mock ACME fixtures。"""

import json

import pytest
from click.testing import CliRunner
from unittest.mock import MagicMock, patch

from acps_ca_client.keys import generate_private_key, save_private_key


@pytest.fixture
def runner():
    """返回一个 Click CliRunner 实例。"""
    return CliRunner()


@pytest.fixture
def mock_acme_responses():
    """
    构造一套完整的 mock ACME 交互序列。
    返回一个 dict，可按需用于 patch AcmeClient 方法。
    """
    return {
        "directory": {
            "newNonce": "http://localhost:8003/acme/new-nonce",
            "newAccount": "http://localhost:8003/acme/new-acct",
            "newOrder": "http://localhost:8003/acme/new-order",
            "revokeCert": "http://localhost:8003/acme/revoke-cert",
            "keyChange": "http://localhost:8003/acme/key-change",
        },
        "account": {
            "status": "valid",
            "contact": [],
        },
        "order": {
            "status": "ready",
            "authorizations": ["http://localhost:8003/acme/authz/1"],
            "finalize": "http://localhost:8003/acme/order/1/finalize",
            "url": "http://localhost:8003/acme/order/1",
        },
        "authorization": {
            "status": "pending",
            "challenges": [
                {
                    "type": "http-01",
                    "url": "http://localhost:8003/acme/chall/1",
                    "token": "test-token-abc123",
                }
            ],
        },
        "authorization_valid": {
            "status": "valid",
            "challenges": [
                {
                    "type": "http-01",
                    "url": "http://localhost:8003/acme/chall/1",
                    "token": "test-token-abc123",
                    "status": "valid",
                }
            ],
        },
        "order_valid": {
            "status": "valid",
            "certificate": "http://localhost:8003/acme/cert/1",
            "url": "http://localhost:8003/acme/order/1",
        },
    }


@pytest.fixture
def setup_account_key(tmp_workspace):
    """在临时工作空间中预生成 account key。"""
    key = generate_private_key("ec")
    key_path = str(tmp_workspace / "private" / "account.key")
    save_private_key(key, key_path)
    return key_path, key
