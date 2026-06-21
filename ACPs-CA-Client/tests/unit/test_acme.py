"""单元测试 — acme 模块（base64url、JWK、JWS、AcmeError）。"""

import json
import base64

import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from acps_ca_client.keys import generate_private_key
from acps_ca_client.acme import (
    base64url_encode,
    get_jwk,
    get_jwk_thumbprint,
    AcmeClient,
    AcmeError,
)


# ---------------------------------------------------------------------------
# base64url_encode
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestBase64UrlEncode:
    def test_encode_bytes(self):
        result = base64url_encode(b"\x00\x01\x02")
        assert isinstance(result, str)
        # 不应包含 padding '='
        assert "=" not in result

    def test_encode_string(self):
        result = base64url_encode("hello")
        decoded = base64.urlsafe_b64decode(result + "==")
        assert decoded == b"hello"

    def test_empty_input(self):
        assert base64url_encode(b"") == ""

    def test_url_safe_characters(self):
        # 包含 +/ 的源数据在 base64url 中应被替换为 -_
        data = b"\xfb\xff\xfe"
        result = base64url_encode(data)
        assert "+" not in result
        assert "/" not in result


# ---------------------------------------------------------------------------
# get_jwk
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestGetJWK:
    def test_ec_key_jwk_fields(self):
        key = generate_private_key("ec")
        jwk = get_jwk(key)
        assert jwk["kty"] == "EC"
        assert jwk["crv"] == "P-256"
        assert "x" in jwk
        assert "y" in jwk

    def test_rsa_key_jwk_fields(self):
        key = generate_private_key("rsa")
        jwk = get_jwk(key)
        assert jwk["kty"] == "RSA"
        assert "n" in jwk
        assert "e" in jwk

    def test_unsupported_key_type_raises(self):
        with pytest.raises(ValueError, match="Unsupported key type"):
            get_jwk("not-a-key")


# ---------------------------------------------------------------------------
# get_jwk_thumbprint
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestGetJWKThumbprint:
    def test_deterministic(self):
        key = generate_private_key("ec")
        jwk = get_jwk(key)
        t1 = get_jwk_thumbprint(jwk)
        t2 = get_jwk_thumbprint(jwk)
        assert t1 == t2

    def test_different_keys_different_thumbprints(self):
        k1 = generate_private_key("ec")
        k2 = generate_private_key("ec")
        t1 = get_jwk_thumbprint(get_jwk(k1))
        t2 = get_jwk_thumbprint(get_jwk(k2))
        assert t1 != t2


# ---------------------------------------------------------------------------
# AcmeClient._build_jws (class method, no network)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestBuildJWS:
    def test_jws_structure_with_jwk(self):
        key = generate_private_key("ec")
        jwk = get_jwk(key)
        jws = AcmeClient._build_jws(
            key=key,
            payload={"test": "data"},
            url="https://example.com/acme/new-acct",
            nonce="fake-nonce",
            jwk=jwk,
        )
        assert "protected" in jws
        assert "payload" in jws
        assert "signature" in jws

        # 解码 protected header 验证内容
        protected_json = base64.urlsafe_b64decode(jws["protected"] + "==")
        protected = json.loads(protected_json)
        assert protected["alg"] == "ES256"
        assert protected["nonce"] == "fake-nonce"
        assert protected["url"] == "https://example.com/acme/new-acct"
        assert "jwk" in protected

    def test_jws_structure_with_kid(self):
        key = generate_private_key("ec")
        jws = AcmeClient._build_jws(
            key=key,
            payload=None,
            url="https://example.com/acme/orders/1",
            nonce="nonce-2",
            kid="https://example.com/acme/acct/123",
        )
        protected_json = base64.urlsafe_b64decode(jws["protected"] + "==")
        protected = json.loads(protected_json)
        assert protected["kid"] == "https://example.com/acme/acct/123"
        assert "jwk" not in protected
        # payload 应为空字符串 (POST-as-GET)
        assert jws["payload"] == ""

    def test_jws_rsa_key(self):
        key = generate_private_key("rsa")
        jwk = get_jwk(key)
        jws = AcmeClient._build_jws(
            key=key,
            payload={"foo": "bar"},
            nonce="n",
            jwk=jwk,
        )
        protected_json = base64.urlsafe_b64decode(jws["protected"] + "==")
        protected = json.loads(protected_json)
        assert protected["alg"] == "RS256"

    def test_jws_requires_kid_or_jwk(self):
        key = generate_private_key("ec")
        with pytest.raises(ValueError, match="Either kid or jwk"):
            AcmeClient._build_jws(key=key, payload={})


# ---------------------------------------------------------------------------
# AcmeClient 初始化
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestAcmeClientInit:
    def test_init_with_key(self):
        key = generate_private_key("ec")
        client = AcmeClient("http://localhost:8003", key)
        assert client.ca_server_url == "http://localhost:8003"
        assert client.jwk is not None
        assert client.thumbprint is not None
        assert client.directory is None
        assert client.account_url is None

    def test_init_strips_trailing_slash(self):
        key = generate_private_key("ec")
        client = AcmeClient("http://localhost:8003/", key)
        assert client.ca_server_url == "http://localhost:8003"

    def test_init_without_key(self):
        client = AcmeClient("http://localhost:8003", None)
        assert client.jwk is None
        assert client.thumbprint is None


# ---------------------------------------------------------------------------
# AcmeError
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestAcmeError:
    def test_basic_message(self):
        err = AcmeError("something failed")
        assert str(err) == "something failed"

    def test_with_detail(self):
        err = AcmeError("failed", status_code=400, detail={"type": "badCSR"})
        assert "Detail" in str(err)
        assert err.status_code == 400

    def test_without_detail(self):
        err = AcmeError("fail", status_code=500)
        assert "Detail" not in str(err)
