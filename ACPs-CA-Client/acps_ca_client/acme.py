import json
import base64
import hashlib
import time
import logging
import requests
from cryptography import x509
from cryptography.x509 import ocsp
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, ec, padding
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

logger = logging.getLogger(__name__)


def base64url_encode(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def get_jwk(private_key):
    if isinstance(private_key, rsa.RSAPrivateKey):
        pn = private_key.private_numbers()
        return {
            "e": base64url_encode(
                pn.public_numbers.e.to_bytes(
                    (pn.public_numbers.e.bit_length() + 7) // 8, "big"
                )
            ),
            "kty": "RSA",
            "n": base64url_encode(
                pn.public_numbers.n.to_bytes(
                    (pn.public_numbers.n.bit_length() + 7) // 8, "big"
                )
            ),
        }
    elif isinstance(private_key, ec.EllipticCurvePrivateKey):
        pn = private_key.private_numbers()
        return {
            "crv": "P-256",
            "kty": "EC",
            "x": base64url_encode(pn.public_numbers.x.to_bytes(32, "big")),
            "y": base64url_encode(pn.public_numbers.y.to_bytes(32, "big")),
        }
    raise ValueError("Unsupported key type")


def get_jwk_thumbprint(jwk):
    # Sort keys and remove whitespace for canonical JSON
    canonical_json = json.dumps(jwk, sort_keys=True, separators=(",", ":"))
    return base64url_encode(hashlib.sha256(canonical_json.encode("utf-8")).digest())


class AcmeError(Exception):
    def __init__(self, message, status_code=None, detail=None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail

    def __str__(self):
        if self.detail:
            return f"{super().__str__()} - Detail: {self.detail}"
        return super().__str__()


class AcmeClient:
    def __init__(self, ca_server_url, account_key):
        self.ca_server_url = ca_server_url.rstrip("/")
        self.account_key = account_key
        if account_key:
            self.jwk = get_jwk(account_key)
            self.thumbprint = get_jwk_thumbprint(self.jwk)
        else:
            self.jwk = None
            self.thumbprint = None
        self.directory = None
        self.account_url = None
        self.nonce = None

    def get_directory(self):
        if not self.directory:
            url = f"{self.ca_server_url}/acme/directory"
            logger.debug(f"Fetching ACME directory from {url}")
            resp = requests.get(url)
            resp.raise_for_status()
            self.directory = resp.json()
            logger.debug(f"Directory endpoints: {list(self.directory.keys())}")
        return self.directory

    def get_nonce(self):
        directory = self.get_directory()
        logger.debug(f"Fetching new nonce from {directory['newNonce']}")
        resp = requests.head(directory["newNonce"])
        resp.raise_for_status()
        self.nonce = resp.headers["Replay-Nonce"]
        logger.debug(f"Got nonce: {self.nonce}")
        return self.nonce

    def _sign_request(self, url, payload):
        if not self.account_key:
            raise ValueError("Account key is required for signed ACME requests")

        if not self.nonce:
            self.get_nonce()

        kid = self.account_url if self.account_url else None
        jwk = None if kid else self.jwk
        data = self._build_jws(
            key=self.account_key,
            url=url,
            payload=payload,
            nonce=self.nonce,
            kid=kid,
            jwk=jwk,
        )
        return data

    @staticmethod
    def _algorithm_for_key(key):
        if isinstance(key, rsa.RSAPrivateKey):
            return "RS256"
        if isinstance(key, ec.EllipticCurvePrivateKey):
            return "ES256"
        raise ValueError("Unsupported key type for signing")

    @staticmethod
    def _sign_bytes(key, data):
        if isinstance(key, rsa.RSAPrivateKey):
            return key.sign(data, padding.PKCS1v15(), hashes.SHA256())
        if isinstance(key, ec.EllipticCurvePrivateKey):
            signature = key.sign(data, ec.ECDSA(hashes.SHA256()))
            r, s = decode_dss_signature(signature)
            curve_size = key.curve.key_size // 8
            return r.to_bytes(curve_size, "big") + s.to_bytes(curve_size, "big")
        raise ValueError("Unsupported key type for signing")

    @classmethod
    def _build_jws(cls, key, payload, url=None, nonce=None, kid=None, jwk=None):
        if not kid and not jwk:
            raise ValueError("Either kid or jwk must be provided for a JWS header")

        protected = {
            "alg": cls._algorithm_for_key(key),
        }

        if nonce is not None:
            protected["nonce"] = nonce
        if url is not None:
            protected["url"] = url

        if kid:
            protected["kid"] = kid
        if jwk:
            protected["jwk"] = jwk

        if payload is None:
            payload_b64 = ""
        else:
            payload_b64 = base64url_encode(json.dumps(payload).encode("utf-8"))

        protected_b64 = base64url_encode(json.dumps(protected).encode("utf-8"))
        signing_input = f"{protected_b64}.{payload_b64}".encode("utf-8")
        signature = cls._sign_bytes(key, signing_input)

        return {
            "protected": protected_b64,
            "payload": payload_b64,
            "signature": base64url_encode(signature),
        }

    def _post(self, url, payload):
        data = self._sign_request(url, payload)
        headers = {"Content-Type": "application/jose+json"}
        logger.debug(f"POST {url}")
        resp = requests.post(url, json=data, headers=headers)
        logger.debug(f"Response: {resp.status_code}")

        # Update nonce from response header
        if "Replay-Nonce" in resp.headers:
            self.nonce = resp.headers["Replay-Nonce"]
        else:
            self.nonce = None  # Force fetch new nonce next time if missing

        if resp.status_code not in [200, 201]:
            try:
                error_detail = resp.json()
            except:
                error_detail = resp.text
            logger.debug(f"Error response body: {error_detail}")
            raise AcmeError(
                f"ACME Request Failed: {resp.status_code} {url}",
                resp.status_code,
                error_detail,
            )

        return resp

    def new_account(
        self, contact=None, terms_of_service_agreed=True, only_return_existing=False
    ):
        directory = self.get_directory()
        payload = {
            "termsOfServiceAgreed": terms_of_service_agreed,
            "onlyReturnExisting": only_return_existing,
        }
        if contact:
            payload["contact"] = contact

        logger.debug(
            f"Account request to {directory['newAccount']} (onlyReturnExisting={only_return_existing})"
        )
        resp = self._post(directory["newAccount"], payload)
        self.account_url = resp.headers.get("Location", self.account_url)
        logger.debug(f"Account URL: {self.account_url}")
        return resp.json()

    def new_order(self, aic):
        directory = self.get_directory()
        payload = {"identifiers": [{"type": "agent", "value": aic}]}
        logger.debug(
            f"Creating order at {directory['newOrder']} for identifier: agent={aic}"
        )
        resp = self._post(directory["newOrder"], payload)
        order = resp.json()
        order["url"] = resp.headers["Location"]
        logger.debug(f"Order URL: {order['url']}")
        logger.debug(
            f"Order status: {order.get('status')}, authorizations: {order.get('authorizations')}"
        )
        return order

    def get_authorization(self, authz_url):
        # POST-as-GET
        logger.debug(f"Fetching authorization from {authz_url}")
        resp = self._post(authz_url, None)
        authz = resp.json()
        logger.debug(
            f"Authorization status: {authz.get('status')}, challenges: {len(authz.get('challenges', []))}"
        )
        return authz

    def respond_challenge(self, challenge_url):
        logger.debug(f"Responding to challenge at {challenge_url}")
        resp = self._post(challenge_url, {})
        return resp.json()

    def finalize_order(self, finalize_url, csr_pem):
        logger.debug(f"Finalizing order at {finalize_url}")
        # CSR needs to be DER encoded and then base64url encoded
        # csr_pem is bytes
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization

        csr = x509.load_pem_x509_csr(csr_pem)
        csr_der = csr.public_bytes(serialization.Encoding.DER)

        payload = {"csr": base64url_encode(csr_der)}
        resp = self._post(finalize_url, payload)
        return resp.json()

    def get_certificate(self, cert_url):
        # POST-as-GET
        logger.debug(f"Downloading certificate from {cert_url}")
        resp = self._post(cert_url, None)
        return resp.content  # PEM content

    def revoke_cert(self, cert_pem, reason=0):
        directory = self.get_directory()
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization

        cert = x509.load_pem_x509_certificate(cert_pem)
        cert_der = cert.public_bytes(serialization.Encoding.DER)

        payload = {"certificate": base64url_encode(cert_der), "reason": reason}
        logger.debug(
            f"Revoking certificate at {directory['revokeCert']} (reason={reason})"
        )
        self._post(directory["revokeCert"], payload)

    def key_change(self, new_key):
        if not self.account_url:
            raise AcmeError(
                "Account URL is unknown. Call new_account(only_return_existing=True) before key rollover."
            )

        directory = self.get_directory()
        key_change_url = directory["keyChange"]
        logger.debug(f"Requesting key change at {key_change_url}")
        logger.debug(f"Account URL: {self.account_url}")

        inner_payload = {
            "account": self.account_url,
            "oldKey": self.jwk,
        }

        new_jwk = get_jwk(new_key)
        inner_jws = self._build_jws(
            key=new_key,
            payload=inner_payload,
            jwk=new_jwk,
        )

        outer_nonce = self.get_nonce()
        outer_jws = self._build_jws(
            key=self.account_key,
            payload=inner_jws,
            url=key_change_url,
            nonce=outer_nonce,
            kid=self.account_url,
        )

        headers = {"Content-Type": "application/jose+json"}
        logger.debug(f"POST {key_change_url}")
        resp = requests.post(key_change_url, json=outer_jws, headers=headers)
        logger.debug(f"Response: {resp.status_code}")

        if "Replay-Nonce" in resp.headers:
            self.nonce = resp.headers["Replay-Nonce"]
        else:
            self.nonce = None

        if resp.status_code not in [200, 201]:
            try:
                error_detail = resp.json()
            except Exception:
                error_detail = resp.text
            raise AcmeError(
                f"ACME Key Rollover Failed: {resp.status_code} {key_change_url}",
                resp.status_code,
                error_detail,
            )

        self.account_key = new_key
        self.jwk = new_jwk
        self.thumbprint = get_jwk_thumbprint(new_jwk)
        logger.debug("Key change completed, local client state updated")

        return resp.json()

    def download_crl(self, format="der"):
        url = f"{self.ca_server_url}/crl"
        logger.debug(f"Downloading CRL from {url} (format={format})")
        resp = requests.get(url, params={"format": format})
        resp.raise_for_status()
        logger.debug(f"CRL downloaded: {len(resp.content)} bytes")
        return resp.content

    def check_ocsp(self, cert_pem, issuer_pem):
        cert = x509.load_pem_x509_certificate(cert_pem)
        issuer = x509.load_pem_x509_certificate(issuer_pem)

        builder = ocsp.OCSPRequestBuilder()
        builder = builder.add_certificate(cert, issuer, hashes.SHA1())
        req = builder.build()

        req_der = req.public_bytes(serialization.Encoding.DER)

        url = f"{self.ca_server_url}/ocsp"
        logger.debug(f"Sending OCSP request to {url}")
        headers = {"Content-Type": "application/ocsp-request"}
        resp = requests.post(url, data=req_der, headers=headers)
        logger.debug(f"OCSP response: {resp.status_code}")

        if not resp.ok:
            raise AcmeError(
                f"OCSP Request Failed: {resp.status_code}", resp.status_code, resp.text
            )

        return ocsp.load_der_ocsp_response(resp.content)
