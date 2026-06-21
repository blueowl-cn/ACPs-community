"""单元测试 — Config 配置加载。"""

import os
import sys

import pytest

from acps_ca_client.config import Config


@pytest.mark.unit
class TestConfigLoading:
    def test_load_from_explicit_path(self, tmp_path):
        conf = tmp_path / "my.conf"
        conf.write_text(
            "CA_SERVER_BASE_URL = http://localhost:8003\n"
            "CHALLENGE_SERVER_BASE_URL = http://localhost:8004\n"
        )
        cfg = Config(str(conf))
        assert cfg.ca_server_url == "http://localhost:8003"
        assert cfg.challenge_server_url == "http://localhost:8004"

    def test_default_values(self, tmp_path):
        conf = tmp_path / "minimal.conf"
        conf.write_text(
            "CA_SERVER_BASE_URL = http://localhost:8003\n"
            "CHALLENGE_SERVER_BASE_URL = http://localhost:8004\n"
        )
        cfg = Config(str(conf))
        assert cfg.account_key_path == "./private/account.key"
        assert cfg.certs_dir == "./certs"
        assert cfg.private_keys_dir == "./private"
        assert cfg.csr_dir == "./csr"
        assert cfg.trust_bundle_path == "./certs/trust-bundle.pem"
        assert cfg.challenge_deploy_mock is False

    def test_override_defaults(self, tmp_path):
        conf = tmp_path / "full.conf"
        conf.write_text(
            "CA_SERVER_BASE_URL = https://ca.example.com\n"
            "CHALLENGE_SERVER_BASE_URL = https://ch.example.com\n"
            "ACCOUNT_KEY_PATH = /etc/keys/account.key\n"
            "CERTS_DIR = /etc/certs\n"
            "PRIVATE_KEYS_DIR = /etc/private\n"
            "CSR_DIR = /etc/csr\n"
            "TRUST_BUNDLE_PATH = /etc/certs/bundle.pem\n"
            "CHALLENGE_DEPLOY_MOCK = true\n"
        )
        cfg = Config(str(conf))
        assert cfg.account_key_path == "/etc/keys/account.key"
        assert cfg.certs_dir == "/etc/certs"
        assert cfg.private_keys_dir == "/etc/private"
        assert cfg.csr_dir == "/etc/csr"
        assert cfg.trust_bundle_path == "/etc/certs/bundle.pem"
        assert cfg.challenge_deploy_mock is True

    def test_comments_and_blank_lines_ignored(self, tmp_path):
        conf = tmp_path / "commented.conf"
        conf.write_text(
            "# This is a comment\n"
            "\n"
            "CA_SERVER_BASE_URL = http://localhost:8003\n"
            "# Another comment\n"
            "CHALLENGE_SERVER_BASE_URL = http://localhost:8004\n"
            "\n"
        )
        cfg = Config(str(conf))
        assert cfg.ca_server_url == "http://localhost:8003"

    def test_missing_file_does_not_crash(self, tmp_path):
        cfg = Config(str(tmp_path / "nonexistent.conf"))
        # No exception, just empty config
        assert cfg.get("CA_SERVER_BASE_URL") is None


@pytest.mark.unit
class TestConfigChallengeMock:
    def test_mock_false_by_default(self, tmp_path):
        conf = tmp_path / "c.conf"
        conf.write_text(
            "CA_SERVER_BASE_URL = http://localhost:8003\n"
            "CHALLENGE_SERVER_BASE_URL = http://localhost:8004\n"
        )
        cfg = Config(str(conf))
        assert cfg.challenge_deploy_mock is False

    def test_mock_true(self, tmp_path):
        conf = tmp_path / "c.conf"
        conf.write_text(
            "CHALLENGE_DEPLOY_MOCK = true\n"
            "CA_SERVER_BASE_URL = http://localhost:8003\n"
            "CHALLENGE_SERVER_BASE_URL = http://localhost:8004\n"
        )
        cfg = Config(str(conf))
        assert cfg.challenge_deploy_mock is True

    def test_mock_case_insensitive(self, tmp_path):
        conf = tmp_path / "c.conf"
        conf.write_text(
            "CHALLENGE_DEPLOY_MOCK = True\n"
            "CA_SERVER_BASE_URL = http://localhost:8003\n"
            "CHALLENGE_SERVER_BASE_URL = http://localhost:8004\n"
        )
        cfg = Config(str(conf))
        assert cfg.challenge_deploy_mock is True

    def test_mock_false_explicit(self, tmp_path):
        conf = tmp_path / "c.conf"
        conf.write_text(
            "CHALLENGE_DEPLOY_MOCK = false\n"
            "CA_SERVER_BASE_URL = http://localhost:8003\n"
            "CHALLENGE_SERVER_BASE_URL = http://localhost:8004\n"
        )
        cfg = Config(str(conf))
        assert cfg.challenge_deploy_mock is False


@pytest.mark.unit
class TestConfigValidation:
    def test_missing_ca_server_url_exits(self, tmp_path):
        conf = tmp_path / "c.conf"
        conf.write_text("CHALLENGE_SERVER_BASE_URL = http://localhost:8004\n")
        cfg = Config(str(conf))
        with pytest.raises(SystemExit):
            _ = cfg.ca_server_url

    def test_invalid_url_exits(self, tmp_path):
        conf = tmp_path / "c.conf"
        conf.write_text(
            "CA_SERVER_BASE_URL = not-a-url\n"
            "CHALLENGE_SERVER_BASE_URL = http://localhost:8004\n"
        )
        cfg = Config(str(conf))
        with pytest.raises(SystemExit):
            _ = cfg.ca_server_url

    def test_value_with_spaces_around_equals(self, tmp_path):
        conf = tmp_path / "c.conf"
        conf.write_text(
            "CA_SERVER_BASE_URL   =   http://localhost:8003  \n"
            "CHALLENGE_SERVER_BASE_URL = http://localhost:8004\n"
        )
        cfg = Config(str(conf))
        assert cfg.ca_server_url == "http://localhost:8003"
