"""集成测试 — 通过 Click CliRunner 测试 CLI 子命令。

所有网络交互（AcmeClient、requests）均通过 mock 替换，验证：
- CLI 参数解析与校验
- 子命令执行流程的正确衔接
- 文件输出和提示信息
"""

import os
import json
from unittest.mock import patch, MagicMock, PropertyMock

import pytest
from click.testing import CliRunner
from cryptography.hazmat.primitives import serialization

from acps_ca_client.cli import main
from acps_ca_client.keys import generate_private_key, save_private_key


# ---------------------------------------------------------------------------
# help / 全局参数
# ---------------------------------------------------------------------------
@pytest.mark.integration
class TestCLIGlobal:
    def test_help(self, runner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "new-cert" in result.output
        assert "renew-cert" in result.output
        assert "revoke-cert" in result.output

    def test_new_cert_help(self, runner):
        result = runner.invoke(main, ["new-cert", "--help"])
        assert result.exit_code == 0
        assert "--aic" in result.output
        assert "--key-path" in result.output
        assert "--cert-path" in result.output
        assert "--trust-bundle-path" in result.output

    def test_revoke_cert_help(self, runner):
        result = runner.invoke(main, ["revoke-cert", "--help"])
        assert result.exit_code == 0
        assert "--reason" in result.output

    def test_key_rollover_help(self, runner):
        result = runner.invoke(main, ["key-rollover", "--help"])
        assert result.exit_code == 0
        assert "--new-key" in result.output
        assert "--backup" in result.output

    def test_download_crl_help(self, runner):
        result = runner.invoke(main, ["download-crl", "--help"])
        assert result.exit_code == 0
        assert "--format" in result.output

    def test_check_ocsp_help(self, runner):
        result = runner.invoke(main, ["check-ocsp", "--help"])
        assert result.exit_code == 0
        assert "--cert" in result.output
        assert "--issuer" in result.output

    def test_new_cert_missing_aic(self, runner, config_file):
        result = runner.invoke(main, ["--config", config_file, "new-cert"])
        assert result.exit_code != 0
        assert "Missing" in result.output or "required" in result.output.lower() or "aic" in result.output.lower()


# ---------------------------------------------------------------------------
# new-cert（mock ACME 交互）
# ---------------------------------------------------------------------------
@pytest.mark.integration
class TestNewCert:
    """场景一 & 场景三：首次申请证书，含自定义输出路径。"""

    def _build_mock_client(self, mock_acme_responses, cert_content=b"-----BEGIN CERTIFICATE-----\nMOCK\n-----END CERTIFICATE-----\n"):
        """构建一个 mock AcmeClient 实例。"""
        mock_client = MagicMock()
        mock_client.thumbprint = "fake-thumbprint"

        # get_directory / get_nonce 不需要特殊返回值

        # new_account 成功
        mock_client.new_account.return_value = mock_acme_responses["account"]

        # new_order 返回带 authorizations 的 order
        mock_client.new_order.return_value = mock_acme_responses["order"]

        # get_authorization 第一次返回 pending，之后返回 valid
        mock_client.get_authorization.side_effect = [
            mock_acme_responses["authorization"],
            mock_acme_responses["authorization_valid"],
        ]

        mock_client.respond_challenge.return_value = {}

        # finalize_order 返回 valid order
        mock_client.finalize_order.return_value = mock_acme_responses["order_valid"]

        # get_certificate 返回 PEM
        mock_client.get_certificate.return_value = cert_content

        return mock_client

    @patch("acps_ca_client.cli.requests")
    @patch("acps_ca_client.cli.AcmeClient")
    def test_new_cert_default_paths(
        self, MockAcmeClient, mock_requests, runner, config_file, sample_aic,
        tmp_workspace, mock_acme_responses,
    ):
        mock_client = self._build_mock_client(mock_acme_responses)
        MockAcmeClient.return_value = mock_client

        # mock trust-bundle 下载
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.content = b"TRUST-BUNDLE-CONTENT"
        mock_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_resp

        result = runner.invoke(
            main, ["--config", config_file, "new-cert", "--aic", sample_aic]
        )
        assert result.exit_code == 0, f"Output: {result.output}\nStderr: {getattr(result, "stderr", "")}"

        # 验证文件生成
        assert os.path.exists(str(tmp_workspace / "private" / f"{sample_aic}.key"))
        assert os.path.exists(str(tmp_workspace / "csr" / f"{sample_aic}.csr"))
        assert os.path.exists(str(tmp_workspace / "certs" / f"{sample_aic}.pem"))

        # 验证 ACME 交互序列
        mock_client.new_account.assert_called_once()
        mock_client.new_order.assert_called_once_with(sample_aic)
        mock_client.respond_challenge.assert_called_once()
        mock_client.finalize_order.assert_called_once()
        mock_client.get_certificate.assert_called_once()

    @patch("acps_ca_client.cli.requests")
    @patch("acps_ca_client.cli.AcmeClient")
    def test_new_cert_custom_output_paths(
        self, MockAcmeClient, mock_requests, runner, config_file, sample_aic,
        tmp_workspace, mock_acme_responses,
    ):
        mock_client = self._build_mock_client(mock_acme_responses)
        MockAcmeClient.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.content = b"TRUST-BUNDLE"
        mock_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_resp

        custom_key = str(tmp_workspace / "custom" / "agent.key")
        custom_cert = str(tmp_workspace / "custom" / "agent.pem")
        custom_bundle = str(tmp_workspace / "custom" / "trust.pem")

        result = runner.invoke(
            main,
            [
                "--config", config_file,
                "new-cert",
                "--aic", sample_aic,
                "--key-path", custom_key,
                "--cert-path", custom_cert,
                "--trust-bundle-path", custom_bundle,
            ],
        )
        assert result.exit_code == 0, f"Output: {result.output}\nStderr: {getattr(result, "stderr", "")}"

        assert os.path.exists(custom_key)
        assert os.path.exists(custom_cert)
        # trust bundle 经 update_trust_bundle 子命令写入
        assert os.path.exists(custom_bundle)

    @patch("acps_ca_client.cli.requests")
    @patch("acps_ca_client.cli.AcmeClient")
    def test_new_cert_reuses_existing_account_key(
        self, MockAcmeClient, mock_requests, runner, config_file, sample_aic,
        tmp_workspace, setup_account_key, mock_acme_responses,
    ):
        mock_client = self._build_mock_client(mock_acme_responses)
        MockAcmeClient.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.content = b"BUNDLE"
        mock_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_resp

        result = runner.invoke(
            main, ["--config", config_file, "new-cert", "--aic", sample_aic]
        )
        assert result.exit_code == 0
        assert "Loading account key" in result.output

    @patch("acps_ca_client.cli.requests")
    @patch("acps_ca_client.cli.AcmeClient")
    def test_new_cert_rsa_key_type(
        self, MockAcmeClient, mock_requests, runner, config_file, sample_aic,
        tmp_workspace, mock_acme_responses,
    ):
        mock_client = self._build_mock_client(mock_acme_responses)
        MockAcmeClient.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.content = b"BUNDLE"
        mock_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_resp

        result = runner.invoke(
            main,
            ["--config", config_file, "new-cert", "--aic", sample_aic, "--key-type", "rsa"],
        )
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# renew-cert
# ---------------------------------------------------------------------------
@pytest.mark.integration
class TestRenewCert:
    """场景五：证书续期（复用 new-cert 逻辑）。"""

    @patch("acps_ca_client.cli.requests")
    @patch("acps_ca_client.cli.AcmeClient")
    def test_renew_cert_invokes_new_cert(
        self, MockAcmeClient, mock_requests, runner, config_file, sample_aic,
        tmp_workspace, mock_acme_responses,
    ):
        mock_client = MagicMock()
        mock_client.thumbprint = "fake-thumbprint"
        mock_client.new_account.return_value = {"status": "valid"}
        mock_client.new_order.return_value = mock_acme_responses["order"]
        mock_client.get_authorization.side_effect = [
            mock_acme_responses["authorization"],
            mock_acme_responses["authorization_valid"],
        ]
        mock_client.respond_challenge.return_value = {}
        mock_client.finalize_order.return_value = mock_acme_responses["order_valid"]
        mock_client.get_certificate.return_value = b"CERT"
        MockAcmeClient.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.content = b"BUNDLE"
        mock_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_resp

        result = runner.invoke(
            main, ["--config", config_file, "renew-cert", "--aic", sample_aic]
        )
        assert result.exit_code == 0
        # renew-cert 内部调用 new-cert，应执行完整 ACME 流程
        mock_client.new_order.assert_called_once_with(sample_aic)


# ---------------------------------------------------------------------------
# revoke-cert
# ---------------------------------------------------------------------------
@pytest.mark.integration
class TestRevokeCert:
    """场景六 & 七：吊销证书。"""

    @patch("acps_ca_client.cli.AcmeClient")
    def test_revoke_cert_success(
        self, MockAcmeClient, runner, config_file, sample_aic, tmp_workspace,
    ):
        mock_client = MagicMock()
        mock_client.revoke_cert.return_value = None
        MockAcmeClient.return_value = mock_client

        # 预先创建 account key 和 cert 文件
        key = generate_private_key("ec")
        save_private_key(key, str(tmp_workspace / "private" / "account.key"))
        cert_path = str(tmp_workspace / "certs" / f"{sample_aic}.pem")
        with open(cert_path, "wb") as f:
            f.write(b"-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----\n")

        result = runner.invoke(
            main, ["--config", config_file, "revoke-cert", "--aic", sample_aic]
        )
        assert result.exit_code == 0
        assert "revoked successfully" in result.output.lower()

    @patch("acps_ca_client.cli.AcmeClient")
    def test_revoke_cert_with_reason(
        self, MockAcmeClient, runner, config_file, sample_aic, tmp_workspace,
    ):
        mock_client = MagicMock()
        mock_client.revoke_cert.return_value = None
        MockAcmeClient.return_value = mock_client

        key = generate_private_key("ec")
        save_private_key(key, str(tmp_workspace / "private" / "account.key"))
        cert_path = str(tmp_workspace / "certs" / f"{sample_aic}.pem")
        with open(cert_path, "wb") as f:
            f.write(b"-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----\n")

        result = runner.invoke(
            main,
            ["--config", config_file, "revoke-cert", "--aic", sample_aic, "--reason", "keyCompromise"],
        )
        assert result.exit_code == 0

    def test_revoke_cert_missing_cert_file(
        self, runner, config_file, sample_aic, tmp_workspace,
    ):
        key = generate_private_key("ec")
        save_private_key(key, str(tmp_workspace / "private" / "account.key"))

        result = runner.invoke(
            main, ["--config", config_file, "revoke-cert", "--aic", sample_aic]
        )
        # 证书文件不存在时应提示而非崩溃
        assert "not found" in result.output.lower() or result.exit_code != 0


# ---------------------------------------------------------------------------
# key-rollover
# ---------------------------------------------------------------------------
@pytest.mark.integration
class TestKeyRollover:
    """场景八：轮换 ACME 账户密钥。"""

    @patch("acps_ca_client.cli.AcmeClient")
    def test_key_rollover_auto_generate(
        self, MockAcmeClient, runner, config_file, tmp_workspace, setup_account_key,
    ):
        mock_client = MagicMock()
        mock_client.new_account.return_value = {"status": "valid"}
        mock_client.key_change.return_value = None
        MockAcmeClient.return_value = mock_client

        result = runner.invoke(
            main, ["--config", config_file, "key-rollover"]
        )
        assert result.exit_code == 0, f"Output: {result.output}\nStderr: {getattr(result, "stderr", "")}"
        assert "completed successfully" in result.output.lower()
        # 旧密钥应被备份
        assert "backup" in result.output.lower()

    @patch("acps_ca_client.cli.AcmeClient")
    def test_key_rollover_no_backup(
        self, MockAcmeClient, runner, config_file, tmp_workspace, setup_account_key,
    ):
        mock_client = MagicMock()
        mock_client.new_account.return_value = {"status": "valid"}
        mock_client.key_change.return_value = None
        MockAcmeClient.return_value = mock_client

        result = runner.invoke(
            main, ["--config", config_file, "key-rollover", "--no-backup"]
        )
        assert result.exit_code == 0
        assert "completed successfully" in result.output.lower()

    @patch("acps_ca_client.cli.AcmeClient")
    def test_key_rollover_with_pregenerated_key(
        self, MockAcmeClient, runner, config_file, tmp_workspace, setup_account_key,
    ):
        mock_client = MagicMock()
        mock_client.new_account.return_value = {"status": "valid"}
        mock_client.key_change.return_value = None
        MockAcmeClient.return_value = mock_client

        # 预生成新密钥文件
        new_key = generate_private_key("ec")
        new_key_path = str(tmp_workspace / "private" / "new.key")
        save_private_key(new_key, new_key_path)

        result = runner.invoke(
            main, ["--config", config_file, "key-rollover", "--new-key", new_key_path]
        )
        assert result.exit_code == 0

    def test_key_rollover_no_account_key(
        self, runner, config_file, tmp_workspace,
    ):
        result = runner.invoke(
            main, ["--config", config_file, "key-rollover"]
        )
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# update-trust-bundle
# ---------------------------------------------------------------------------
@pytest.mark.integration
class TestUpdateTrustBundle:
    """场景九：手动更新信任包。"""

    @patch("acps_ca_client.cli.requests")
    def test_update_trust_bundle(
        self, mock_requests, runner, config_file, tmp_workspace,
    ):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.content = b"-----BEGIN CERTIFICATE-----\nROOT\n-----END CERTIFICATE-----\n"
        mock_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_resp

        result = runner.invoke(
            main, ["--config", config_file, "update-trust-bundle"]
        )
        assert result.exit_code == 0
        assert "updated" in result.output.lower()
        bundle_path = str(tmp_workspace / "certs" / "trust-bundle.pem")
        assert os.path.exists(bundle_path)

    @patch("acps_ca_client.cli.requests")
    def test_update_trust_bundle_custom_output(
        self, mock_requests, runner, config_file, tmp_workspace,
    ):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.content = b"BUNDLE"
        mock_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_resp

        custom_path = str(tmp_workspace / "custom" / "bundle.pem")
        result = runner.invoke(
            main,
            ["--config", config_file, "update-trust-bundle", "--output", custom_path],
        )
        assert result.exit_code == 0
        assert os.path.exists(custom_path)


# ---------------------------------------------------------------------------
# download-crl
# ---------------------------------------------------------------------------
@pytest.mark.integration
class TestDownloadCRL:
    """场景十：下载 CRL。"""

    @patch("acps_ca_client.cli.AcmeClient")
    def test_download_crl_der(
        self, MockAcmeClient, runner, config_file, tmp_workspace,
    ):
        mock_client = MagicMock()
        mock_client.download_crl.return_value = b"\x30\x82"  # DER bytes
        MockAcmeClient.return_value = mock_client

        result = runner.invoke(
            main, ["--config", config_file, "download-crl"]
        )
        assert result.exit_code == 0
        assert os.path.exists(str(tmp_workspace / "certs" / "ca.crl"))

    @patch("acps_ca_client.cli.AcmeClient")
    def test_download_crl_pem_custom_output(
        self, MockAcmeClient, runner, config_file, tmp_workspace,
    ):
        mock_client = MagicMock()
        mock_client.download_crl.return_value = b"-----BEGIN X509 CRL-----\n"
        MockAcmeClient.return_value = mock_client

        custom_path = str(tmp_workspace / "custom" / "my.pem")
        result = runner.invoke(
            main,
            ["--config", config_file, "download-crl", "--format", "pem", "--output", custom_path],
        )
        assert result.exit_code == 0
        assert os.path.exists(custom_path)


# ---------------------------------------------------------------------------
# check-ocsp
# ---------------------------------------------------------------------------
@pytest.mark.integration
class TestCheckOCSP:
    """场景十一：OCSP 查询。"""

    def test_check_ocsp_missing_cert(self, runner, config_file, tmp_workspace):
        result = runner.invoke(
            main,
            [
                "--config", config_file,
                "check-ocsp",
                "--cert", "/nonexistent/cert.pem",
                "--issuer", "/nonexistent/issuer.pem",
            ],
        )
        # 文件不存在时应报错
        assert result.exit_code != 0 or "failed" in result.output.lower() or "error" in result.output.lower() or "No such file" in result.output


# ---------------------------------------------------------------------------
# verbose 模式
# ---------------------------------------------------------------------------
@pytest.mark.integration
class TestVerboseMode:
    """场景十二：调试模式。"""

    @patch("acps_ca_client.cli.requests")
    @patch("acps_ca_client.cli.AcmeClient")
    def test_verbose_flag(
        self, MockAcmeClient, mock_requests, runner, config_file, sample_aic,
        tmp_workspace, mock_acme_responses,
    ):
        mock_client = MagicMock()
        mock_client.thumbprint = "fake"
        mock_client.new_account.return_value = {"status": "valid"}
        mock_client.new_order.return_value = mock_acme_responses["order"]
        mock_client.get_authorization.side_effect = [
            mock_acme_responses["authorization"],
            mock_acme_responses["authorization_valid"],
        ]
        mock_client.respond_challenge.return_value = {}
        mock_client.finalize_order.return_value = mock_acme_responses["order_valid"]
        mock_client.get_certificate.return_value = b"CERT"
        MockAcmeClient.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.content = b"BUNDLE"
        mock_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_resp

        result = runner.invoke(
            main,
            ["--verbose", "--config", config_file, "new-cert", "--aic", sample_aic],
        )
        assert result.exit_code == 0
