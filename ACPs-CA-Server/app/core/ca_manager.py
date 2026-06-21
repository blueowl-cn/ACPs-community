"""
CA 证书管理器

负责管理 CA 根证书和私钥，提供证书签发功能
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict
from pathlib import Path

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, ec
from cryptography.hazmat.backends import default_backend

from .config import get_settings


class CAManager:
    """CA 证书管理器"""

    def __init__(self):
        self.settings = get_settings()
        self.ca_cert: Optional[x509.Certificate] = None
        self.ca_private_key: Optional[rsa.RSAPrivateKey] = None
        self._load_or_create_ca()

    def _load_or_create_ca(self):
        """加载或创建 CA 证书和私钥"""
        ca_cert_path = Path(self.settings.ca_cert_path)
        ca_key_path = Path(self.settings.ca_key_path)

        if ca_cert_path.exists() and ca_key_path.exists():
            self._load_ca_from_files(ca_cert_path, ca_key_path)
        else:
            self._create_ca_certificate(ca_cert_path, ca_key_path)

    def _load_ca_from_files(self, cert_path: Path, key_path: Path):
        """从文件加载 CA 证书和私钥"""
        try:
            # 加载证书
            with open(cert_path, "rb") as f:
                cert_data = f.read()
                self.ca_cert = x509.load_pem_x509_certificate(
                    cert_data, default_backend()
                )

            # 加载私钥
            with open(key_path, "rb") as f:
                key_data = f.read()
                self.ca_private_key = serialization.load_pem_private_key(
                    key_data,
                    password=None,  # 在生产环境中应该使用密码保护
                    backend=default_backend(),
                )

            print(f"已加载 CA 证书: {cert_path}")
            valid_from = self.ca_cert.not_valid_before_utc
            valid_to = self.ca_cert.not_valid_after_utc
            print(f"CA 证书有效期: {valid_from} 至 {valid_to}")

        except Exception as e:
            print(f"加载 CA 证书失败: {e}")
            raise

    def _create_ca_certificate(self, cert_path: Path, key_path: Path):
        """创建新的 CA 根证书"""
        print("创建新的 CA 根证书...")

        # 确保目录存在
        cert_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.parent.mkdir(parents=True, exist_ok=True)

        # 生成私钥
        private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=4096, backend=default_backend()
        )

        # 创建证书主体
        subject = x509.Name(
            [
                x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
                x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Beijing"),
                x509.NameAttribute(NameOID.LOCALITY_NAME, "Beijing"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Agent CA"),
                x509.NameAttribute(
                    NameOID.ORGANIZATIONAL_UNIT_NAME, "Certificate Authority"
                ),
                x509.NameAttribute(NameOID.COMMON_NAME, "Agent CA Root Certificate"),
            ]
        )

        # 创建证书
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)  # 自签名证书
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc))
            .not_valid_after(
                datetime.now(timezone.utc) + timedelta(days=3650)
            )  # 10年有效期
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(
                    private_key.public_key()
                ),
                critical=False,
            )
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=None),
                critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    key_cert_sign=True,
                    crl_sign=True,
                    digital_signature=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    content_commitment=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .sign(private_key, hashes.SHA256(), default_backend())
        )

        # 保存证书
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        # 保存私钥
        with open(key_path, "wb") as f:
            f.write(
                private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),  # 在生产环境中应该加密
                )
            )

        self.ca_cert = cert
        self.ca_private_key = private_key

        print(f"CA 证书已创建并保存到: {cert_path}")
        print(f"CA 私钥已保存到: {key_path}")

    def sign_certificate(
        self,
        csr: x509.CertificateSigningRequest,
        agent_ids: List[str],
        validity_days: int = 49,
        subject_components: Optional[Dict[str, str]] = None,
        agent_endpoints: Optional[List[str]] = None,
    ) -> str:
        """签发证书

        Args:
            csr: 证书签名请求
            agent_ids: Agent ID列表（目前只支持单个Agent）
            validity_days: 证书有效期（天数）
            subject_components: Agent注册信息中的Subject DN组件
            agent_endpoints: Agent端点列表，用于SAN扩展
        """
        if not self.ca_cert or not self.ca_private_key:
            raise RuntimeError("CA 证书或私钥未加载")

        # 验证只支持单个Agent（根据用户要求，多Agent需分别签发）
        if len(agent_ids) != 1:
            raise ValueError("Currently only single agent certificates are supported")

        agent_id = agent_ids[0]

        # 验证CSR公钥算法
        self._validate_csr_public_key(csr)

        # 构造证书Subject DN（以Agent注册信息为准）
        subject = self._build_certificate_subject(agent_id, subject_components)

        # 创建证书
        cert_builder = x509.CertificateBuilder()

        # 设置主体（使用Agent注册信息构造，而非CSR中的信息）
        cert_builder = cert_builder.subject_name(subject)

        # 设置颁发者（CA）
        cert_builder = cert_builder.issuer_name(self.ca_cert.subject)

        # 设置公钥（从 CSR 获取）
        cert_builder = cert_builder.public_key(csr.public_key())

        # 设置序列号
        cert_builder = cert_builder.serial_number(x509.random_serial_number())

        # 设置有效期
        not_before = datetime.now(timezone.utc)
        not_after = not_before + timedelta(days=validity_days)
        cert_builder = cert_builder.not_valid_before(not_before)
        cert_builder = cert_builder.not_valid_after(not_after)

        # 添加标准扩展
        cert_builder = self._add_standard_extensions(cert_builder, csr)

        # 添加Agent特定的SAN扩展
        cert_builder = self._add_agent_san_extensions(
            cert_builder, agent_id, agent_endpoints
        )

        # 签名证书
        certificate = cert_builder.sign(
            private_key=self.ca_private_key,
            algorithm=hashes.SHA256(),
            backend=default_backend(),
        )

        # 返回 PEM 格式的证书
        return certificate.public_bytes(serialization.Encoding.PEM).decode("utf-8")

    def _validate_csr_public_key(self, csr: x509.CertificateSigningRequest):
        """验证CSR中的公钥算法是否安全

        只允许以下算法：
        - RSA 2048位或更高
        - ECDSA P-256, P-384, P-521

        Args:
            csr: 证书签名请求

        Raises:
            ValueError: 如果公钥算法不安全
        """
        public_key = csr.public_key()

        if isinstance(public_key, rsa.RSAPublicKey):
            # RSA 密钥大小检查
            key_size = public_key.key_size
            if key_size < 2048:
                raise ValueError(
                    f"RSA key size {key_size} is too small. Minimum required: 2048 bits"
                )
            if key_size > 4096:
                logging.warning(
                    f"RSA key size {key_size} is very large, consider using smaller keys for performance"
                )

        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            # ECDSA 曲线检查
            curve = public_key.curve
            allowed_curves = [ec.SECP256R1(), ec.SECP384R1(), ec.SECP521R1()]

            # 检查曲线类型
            curve_allowed = False
            for allowed_curve in allowed_curves:
                if isinstance(curve, type(allowed_curve)):
                    curve_allowed = True
                    break

            if not curve_allowed:
                raise ValueError(
                    f"ECDSA curve {curve.name} is not allowed. "
                    f"Allowed curves: P-256, P-384, P-521"
                )
        else:
            # 不支持的公钥类型
            raise ValueError(
                f"Public key algorithm {type(public_key).__name__} is not supported. "
                f"Only RSA (≥2048 bits) and ECDSA (P-256/P-384/P-521) are allowed"
            )

    def _build_certificate_subject(
        self, agent_id: str, subject_components: Optional[Dict[str, str]] = None
    ) -> x509.Name:
        """构造证书Subject DN"""
        # 基础Subject组件，CN必须是Agent对应的域名
        common_name = self.settings.build_agent_common_name(agent_id)
        name_attributes = [x509.NameAttribute(NameOID.COMMON_NAME, common_name)]

        # 添加Agent注册信息中的组织信息
        if subject_components:
            if "O" in subject_components:
                name_attributes.append(
                    x509.NameAttribute(
                        NameOID.ORGANIZATION_NAME, subject_components["O"]
                    )
                )
            if "OU" in subject_components:
                name_attributes.append(
                    x509.NameAttribute(
                        NameOID.ORGANIZATIONAL_UNIT_NAME, subject_components["OU"]
                    )
                )
            if "C" in subject_components:
                name_attributes.append(
                    x509.NameAttribute(NameOID.COUNTRY_NAME, subject_components["C"])
                )
            if "L" in subject_components:
                name_attributes.append(
                    x509.NameAttribute(NameOID.LOCALITY_NAME, subject_components["L"])
                )
            if "ST" in subject_components:
                name_attributes.append(
                    x509.NameAttribute(
                        NameOID.STATE_OR_PROVINCE_NAME, subject_components["ST"]
                    )
                )

        return x509.Name(name_attributes)

    def _add_standard_extensions(
        self, cert_builder: x509.CertificateBuilder, csr: x509.CertificateSigningRequest
    ) -> x509.CertificateBuilder:
        """添加标准证书扩展"""
        # Subject Key Identifier
        cert_builder = cert_builder.add_extension(
            x509.SubjectKeyIdentifier.from_public_key(csr.public_key()),
            critical=False,
        )

        # Authority Key Identifier
        cert_builder = cert_builder.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                self.ca_private_key.public_key()
            ),
            critical=False,
        )

        # Basic Constraints
        cert_builder = cert_builder.add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )

        # Key Usage（适合Agent证书的用法）
        cert_builder = cert_builder.add_extension(
            x509.KeyUsage(
                key_cert_sign=False,
                crl_sign=False,
                digital_signature=True,  # 用于身份验证和数据签名
                key_encipherment=True,  # 用于密钥协商
                data_encipherment=False,
                key_agreement=False,
                content_commitment=True,  # 用于不可否认性
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )

        # Extended Key Usage（客户端和服务器认证）
        cert_builder = cert_builder.add_extension(
            x509.ExtendedKeyUsage(
                [
                    x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
                    x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
                ]
            ),
            critical=True,
        )

        return cert_builder

    def _add_agent_san_extensions(
        self,
        cert_builder: x509.CertificateBuilder,
        agent_id: str,
        agent_endpoints: Optional[List[str]] = None,
    ) -> x509.CertificateBuilder:
        """添加Agent特定的SAN扩展"""
        san_list = []

        # 添加Agent域名形式的DNS名称
        fqdn = self.settings.build_agent_common_name(agent_id)
        san_list.append(x509.DNSName(fqdn))

        # 添加Agent URI
        san_list.append(x509.UniformResourceIdentifier(f"agent://{agent_id}"))

        # 如果提供了Agent端点，添加到SAN中
        if agent_endpoints:
            for endpoint in agent_endpoints:
                try:
                    # 尝试解析为URI
                    san_list.append(x509.UniformResourceIdentifier(endpoint))
                except Exception:
                    # 如果不是有效URI，尝试作为DNS名称添加
                    try:
                        # 提取hostname部分
                        if endpoint.startswith(("http://", "https://")):
                            from urllib.parse import urlparse

                            parsed = urlparse(endpoint)
                            if parsed.hostname:
                                san_list.append(x509.DNSName(parsed.hostname))
                    except Exception:
                        # 忽略无效的端点
                        pass

        if san_list:
            cert_builder = cert_builder.add_extension(
                x509.SubjectAlternativeName(san_list),
                critical=False,
            )

        return cert_builder

    def get_ca_certificate_pem(self) -> str:
        """获取 CA 证书的 PEM 格式"""
        if not self.ca_cert:
            raise RuntimeError("CA 证书未加载")

        return self.ca_cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")

    def get_ca_private_key_pem(self) -> str:
        """获取 CA 私钥的 PEM 格式"""
        if not self.ca_private_key:
            raise RuntimeError("CA 私钥未加载")

        return self.ca_private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

    def verify_certificate_chain(self, cert_pem: str) -> bool:
        """验证证书链"""
        try:
            # 加载证书
            cert = x509.load_pem_x509_certificate(
                cert_pem.encode("utf-8"), default_backend()
            )

            # 验证是否由当前 CA 签发
            if cert.issuer != self.ca_cert.subject:
                return False

            # 验证签名（这里简化处理，实际应该进行完整的证书链验证）
            try:
                self.ca_private_key.public_key().verify(
                    cert.signature,
                    cert.tbs_certificate_bytes,
                    cert.signature_algorithm_oid._name,
                )
                return True
            except Exception:
                return False

        except Exception:
            return False


# 全局 CA 管理器实例
_ca_manager: Optional[CAManager] = None


def get_ca_manager() -> CAManager:
    """获取 CA 管理器实例"""
    global _ca_manager
    if _ca_manager is None:
        _ca_manager = CAManager()
    return _ca_manager
