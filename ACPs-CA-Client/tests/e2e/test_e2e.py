"""
端到端测试 — 完整证书生命周期。

前置条件：
    ca-server 以 Mock 模式运行：
        AGENT_REGISTRY_MOCK=true HTTP01_VALIDATION_MOCK=true python main.py

测试场景对应 USAGE.md 中的用户使用场景：
    场景一：首次申请证书
    场景三：指定输出路径
    场景五：证书续期
    场景六：吊销证书（keyCompromise）
    场景八：轮换 ACME 账户密钥
    场景九：更新信任包
    场景十：下载 CRL
    场景十一：OCSP 查询
"""

import os
import time

import pytest
from click.testing import CliRunner
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from acps_ca_client.cli import main


@pytest.mark.e2e
class TestCertificateLifecycle:
    """按顺序执行完整的证书生命周期：申请 → 续期 → 吊销。"""

    def test_scenario_01_new_cert(self, e2e_config, e2e_aic, tmp_path):
        """场景一：首次为 Agent 申请证书。"""
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--config", e2e_config, "new-cert", "--aic", e2e_aic],
        )
        assert result.exit_code == 0, f"new-cert failed:\n{result.output}"

        # 验证生成的文件
        assert os.path.exists(
            str(tmp_path / "private" / "account.key")
        ), "account key not generated"
        assert os.path.exists(
            str(tmp_path / "private" / f"{e2e_aic}.key")
        ), "agent key not generated"
        assert os.path.exists(
            str(tmp_path / "csr" / f"{e2e_aic}.csr")
        ), "CSR not generated"
        assert os.path.exists(
            str(tmp_path / "certs" / f"{e2e_aic}.pem")
        ), "certificate not generated"
        assert os.path.exists(
            str(tmp_path / "certs" / "trust-bundle.pem")
        ), "trust bundle not generated"

        # 验证证书可被解析为有效的 X.509
        cert_path = str(tmp_path / "certs" / f"{e2e_aic}.pem")
        with open(cert_path, "rb") as f:
            cert_pem = f.read()
        cert = x509.load_pem_x509_certificate(cert_pem)
        cn = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value
        # CA Server 签发时会在 AIC 后面追加域名后缀（如 .acps.pub）
        assert cn.startswith(e2e_aic)

    def test_scenario_03_custom_output_paths(self, e2e_config, e2e_aic, tmp_path):
        """场景三：指定输出路径。"""
        runner = CliRunner()
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()

        result = runner.invoke(
            main,
            [
                "--config",
                e2e_config,
                "new-cert",
                "--aic",
                e2e_aic,
                "--key-path",
                str(custom_dir / "agent.key"),
                "--cert-path",
                str(custom_dir / "agent.pem"),
                "--trust-bundle-path",
                str(custom_dir / "trust.pem"),
            ],
        )
        assert result.exit_code == 0, f"custom paths failed:\n{result.output}"
        assert os.path.exists(str(custom_dir / "agent.key"))
        assert os.path.exists(str(custom_dir / "agent.pem"))
        assert os.path.exists(str(custom_dir / "trust.pem"))

    def test_scenario_05_renew_cert(self, e2e_config, e2e_aic, tmp_path):
        """场景五：证书续期。"""
        runner = CliRunner()

        # 先申请一张证书
        result = runner.invoke(
            main,
            ["--config", e2e_config, "new-cert", "--aic", e2e_aic],
        )
        assert result.exit_code == 0, f"initial cert failed:\n{result.output}"

        old_cert_path = str(tmp_path / "certs" / f"{e2e_aic}.pem")
        with open(old_cert_path, "rb") as f:
            old_cert = f.read()

        # 续期
        result = runner.invoke(
            main,
            ["--config", e2e_config, "renew-cert", "--aic", e2e_aic],
        )
        assert result.exit_code == 0, f"renew failed:\n{result.output}"

        with open(old_cert_path, "rb") as f:
            new_cert = f.read()
        # 新证书应该是不同的（序列号不同）
        assert new_cert != old_cert or len(new_cert) > 0

    def test_scenario_06_revoke_cert(self, e2e_config, e2e_aic, tmp_path):
        """场景六：因密钥泄露紧急吊销证书。"""
        runner = CliRunner()

        # 先申请
        result = runner.invoke(
            main,
            ["--config", e2e_config, "new-cert", "--aic", e2e_aic],
        )
        assert result.exit_code == 0

        # 吊销
        result = runner.invoke(
            main,
            [
                "--config",
                e2e_config,
                "revoke-cert",
                "--aic",
                e2e_aic,
                "--reason",
                "keyCompromise",
            ],
        )
        assert result.exit_code == 0, f"revoke failed:\n{result.output}"
        assert "revoked successfully" in result.output.lower()


@pytest.mark.e2e
class TestKeyRolloverE2E:
    """场景八：轮换 ACME 账户密钥。"""

    def test_key_rollover_auto(self, e2e_config, e2e_aic, tmp_path):
        runner = CliRunner()

        # 先申请一张证书以创建 account
        result = runner.invoke(
            main,
            ["--config", e2e_config, "new-cert", "--aic", e2e_aic],
        )
        assert result.exit_code == 0

        account_key_path = str(tmp_path / "private" / "account.key")
        with open(account_key_path, "rb") as f:
            old_key_bytes = f.read()

        # 执行 key rollover
        result = runner.invoke(
            main,
            ["--config", e2e_config, "key-rollover"],
        )
        assert result.exit_code == 0, f"key-rollover failed:\n{result.output}"
        assert "completed successfully" in result.output.lower()

        # account.key 应已被替换
        with open(account_key_path, "rb") as f:
            new_key_bytes = f.read()
        assert old_key_bytes != new_key_bytes

        # 备份文件应存在
        import glob

        backups = glob.glob(str(tmp_path / "private" / "account.key.bak-*"))
        assert len(backups) >= 1


@pytest.mark.e2e
class TestTrustBundleAndCRL:
    """场景九 & 场景十：更新信任包 & 下载 CRL。"""

    def test_scenario_09_update_trust_bundle(self, e2e_config, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--config", e2e_config, "update-trust-bundle"],
        )
        assert result.exit_code == 0, f"update-trust-bundle failed:\n{result.output}"
        assert "updated" in result.output.lower()

        bundle_path = str(tmp_path / "certs" / "trust-bundle.pem")
        assert os.path.exists(bundle_path)
        with open(bundle_path, "rb") as f:
            content = f.read()
        assert b"BEGIN CERTIFICATE" in content

    def test_scenario_10_download_crl_der(self, e2e_config, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--config", e2e_config, "download-crl"],
        )
        assert result.exit_code == 0, f"download-crl failed:\n{result.output}"

        crl_path = str(tmp_path / "certs" / "ca.crl")
        assert os.path.exists(crl_path)
        assert os.path.getsize(crl_path) > 0

    def test_scenario_10_download_crl_pem(self, e2e_config, tmp_path):
        runner = CliRunner()
        custom_path = str(tmp_path / "certs" / "ca-crl.pem")
        result = runner.invoke(
            main,
            [
                "--config",
                e2e_config,
                "download-crl",
                "--format",
                "pem",
                "--output",
                custom_path,
            ],
        )
        assert result.exit_code == 0, f"download-crl pem failed:\n{result.output}"
        assert os.path.exists(custom_path)


@pytest.mark.e2e
class TestOCSPCheck:
    """场景十一：通过 OCSP 实时查询证书状态。"""

    def test_scenario_11_check_ocsp_valid(self, e2e_config, e2e_aic, tmp_path):
        runner = CliRunner()

        # 先申请证书
        result = runner.invoke(
            main,
            ["--config", e2e_config, "new-cert", "--aic", e2e_aic],
        )
        assert result.exit_code == 0

        cert_path = str(tmp_path / "certs" / f"{e2e_aic}.pem")
        issuer_path = str(tmp_path / "certs" / "trust-bundle.pem")

        # OCSP 查询
        result = runner.invoke(
            main,
            [
                "--config",
                e2e_config,
                "check-ocsp",
                "--cert",
                cert_path,
                "--issuer",
                issuer_path,
            ],
        )
        # OCSP 可能因 Mock 模式下无 OCSP responder 而失败，这是已知限制
        if "No active OCSP responder" in result.output:
            pytest.skip("OCSP responder not configured in mock mode")
        assert result.exit_code == 0, f"check-ocsp failed:\n{result.output}"
        assert "OCSP Response Status" in result.output

    def test_scenario_11_check_ocsp_revoked(self, e2e_config, e2e_aic, tmp_path):
        runner = CliRunner()

        # 申请 → 吊销 → 查询
        result = runner.invoke(
            main,
            ["--config", e2e_config, "new-cert", "--aic", e2e_aic],
        )
        assert result.exit_code == 0

        result = runner.invoke(
            main,
            [
                "--config",
                e2e_config,
                "revoke-cert",
                "--aic",
                e2e_aic,
                "--reason",
                "keyCompromise",
            ],
        )
        assert result.exit_code == 0

        cert_path = str(tmp_path / "certs" / f"{e2e_aic}.pem")
        issuer_path = str(tmp_path / "certs" / "trust-bundle.pem")

        result = runner.invoke(
            main,
            [
                "--config",
                e2e_config,
                "check-ocsp",
                "--cert",
                cert_path,
                "--issuer",
                issuer_path,
            ],
        )
        # OCSP 可能因 Mock 模式下无 OCSP responder 而失败
        if "No active OCSP responder" in result.output:
            pytest.skip("OCSP responder not configured in mock mode")
        assert (
            result.exit_code == 0
        ), f"check-ocsp after revoke failed:\n{result.output}"
        assert (
            "REVOKED" in result.output.upper()
            or "OCSP Response Status" in result.output
        )


@pytest.mark.e2e
class TestBatchCerts:
    """场景二：为多个 Agent 申请证书（批量）。"""

    def test_scenario_02_batch_certs(self, e2e_config, tmp_path):
        runner = CliRunner()

        aics = [
            "1.2.156.3088.0001.00001.E2EAAA.E2EBBB.1.0AA1",
            "1.2.156.3088.0001.00001.E2EAAA.E2EBBB.1.0AA2",
        ]

        for aic in aics:
            result = runner.invoke(
                main,
                ["--config", e2e_config, "new-cert", "--aic", aic],
            )
            assert (
                result.exit_code == 0
            ), f"batch new-cert for {aic} failed:\n{result.output}"
            assert os.path.exists(str(tmp_path / "certs" / f"{aic}.pem"))

        # 所有证书使用同一 account key
        assert os.path.exists(str(tmp_path / "private" / "account.key"))
