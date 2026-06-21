import os
import sys
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class Config:
    DEFAULT_CONFIG_PATHS = (".ca-client.conf", "ca-client.conf")

    def __init__(self, config_path=None):
        self.config = {}
        self.load(config_path)

    def _resolve_config_path(self, config_path):
        if config_path:
            return config_path

        for candidate in self.DEFAULT_CONFIG_PATHS:
            if os.path.exists(candidate):
                return candidate

        return self.DEFAULT_CONFIG_PATHS[-1]

    def load(self, config_path=None):
        config_path = self._resolve_config_path(config_path)
        if not os.path.exists(config_path):
            logger.debug(f"Config file not found: {config_path}")
            return

        logger.debug(f"Loading configuration from {config_path}")
        with open(config_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    self.config[key.strip()] = value.strip()
        logger.debug(f"Configuration loaded: {len(self.config)} entries")

    def get(self, key, default=None):
        return self.config.get(key, default)

    def _get_required_url(self, key):
        val = self.get(key)
        if not val:
            sys.stderr.write(f"Error: Missing required configuration '{key}'.\n")
            sys.exit(1)

        parsed = urlparse(val)
        if not all([parsed.scheme, parsed.netloc]):
            sys.stderr.write(
                f"Error: Configuration '{key}' is not a valid URL: '{val}'.\n"
            )
            sys.exit(1)
        return val

    @property
    def ca_server_url(self):
        return self._get_required_url("CA_SERVER_BASE_URL")

    @property
    def challenge_server_url(self):
        return self._get_required_url("CHALLENGE_SERVER_BASE_URL")

    @property
    def account_key_path(self):
        return self.get("ACCOUNT_KEY_PATH", "./private/account.key")

    @property
    def certs_dir(self):
        return self.get("CERTS_DIR", "./certs")

    @property
    def private_keys_dir(self):
        return self.get("PRIVATE_KEYS_DIR", "./private")

    @property
    def csr_dir(self):
        return self.get("CSR_DIR", "./csr")

    @property
    def trust_bundle_path(self):
        return self.get("TRUST_BUNDLE_PATH", "./certs/trust-bundle.pem")

    @property
    def challenge_deploy_mock(self):
        return self.get("CHALLENGE_DEPLOY_MOCK", "false").lower() == "true"
