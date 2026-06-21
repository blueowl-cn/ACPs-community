import os
import shutil
import time
import logging
import click
import requests
from cryptography.x509 import ocsp
from .config import Config
from .utils import setup_logging, ensure_directory
from .keys import generate_private_key, save_private_key, load_private_key, generate_csr
from .acme import AcmeClient, get_jwk_thumbprint, AcmeError

logger = logging.getLogger(__name__)


@click.group()
@click.option(
    "--config",
    "-c",
    default=None,
    help="Path to configuration file. Defaults to .ca-client.conf, then ca-client.conf.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
@click.pass_context
def main(ctx, config, verbose):
    setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config"] = Config(config)


def _handle_challenges(
    client, order, challenge_server_url, aic, challenge_deploy_mock=False
):
    """Handle authorizations and challenges for an order."""
    for authz_url in order["authorizations"]:
        authz = client.get_authorization(authz_url)
        if authz["status"] == "valid":
            logger.debug(f"Authorization {authz_url} already valid, skipping")
            continue

        for challenge in authz["challenges"]:
            if challenge["type"] == "http-01":
                token = challenge["token"]
                key_authorization = f"{token}.{client.thumbprint}"
                logger.debug(f"Challenge token: {token}")
                logger.debug(f"Key authorization: {key_authorization}")

                # Deploy challenge response to Challenge Server
                # The design doc says: POST /{aic}/{token} with body key_authorization
                if challenge_deploy_mock:
                    logger.warning(
                        "Challenge deploy mock enabled, skipping challenge deployment"
                    )
                else:
                    challenge_deploy_url = f"{challenge_server_url}/{aic}/{token}"
                    try:
                        logger.info("Deploying challenge response...")
                        # Ensure Content-Type is text/plain as per design
                        headers = {"Content-Type": "text/plain"}

                        logger.debug(f"POST {challenge_deploy_url}")
                        logger.debug(f"Request headers: {headers}")

                        resp = requests.post(
                            challenge_deploy_url,
                            data=key_authorization,
                            headers=headers,
                        )

                        logger.debug(f"Response status: {resp.status_code}")
                        if not resp.ok:
                            logger.debug(f"Response body: {resp.text}")

                        resp.raise_for_status()
                    except Exception as e:
                        raise click.ClickException(
                            f"Failed to deploy challenge response: {e}"
                        )

                # Notify CA Server
                logger.info("Notifying CA server of challenge completion...")
                client.respond_challenge(challenge["url"])

                # Poll for status
                while True:
                    authz = client.get_authorization(authz_url)
                    status = authz["status"]
                    logger.info(f"Authorization status: {status}")
                    if status == "valid":
                        break
                    if status == "invalid":
                        raise click.ClickException(
                            f"Authorization failed: {authz.get('challenges', [{}])[0].get('error')}"
                        )
                    time.sleep(2)
                break


@main.command()
@click.option("--aic", "-a", required=True, help="Agent Identity Code")
@click.option(
    "--key-type", "-k", default="ec", type=click.Choice(["ec", "rsa"]), help="Key type"
)
@click.option(
    "--key-path",
    type=click.Path(dir_okay=False),
    help="Output path for agent private key",
)
@click.option(
    "--cert-path",
    type=click.Path(dir_okay=False),
    help="Output path for certificate chain",
)
@click.option(
    "--trust-bundle-path",
    type=click.Path(dir_okay=False),
    help="Output path for trust bundle",
)
@click.pass_context
def new_cert(ctx, aic, key_type, key_path, cert_path, trust_bundle_path):
    """Request a new certificate for an Agent."""
    cfg = ctx.obj["config"]

    # Resolve output paths (command-line overrides config defaults)
    agent_key_path = key_path or os.path.join(cfg.private_keys_dir, f"{aic}.key")
    final_cert_path = cert_path or os.path.join(cfg.certs_dir, f"{aic}.pem")
    final_trust_bundle_path = trust_bundle_path or cfg.trust_bundle_path
    csr_path = os.path.join(cfg.csr_dir, f"{aic}.csr")

    # Ensure directories exist
    for p in [agent_key_path, csr_path, final_cert_path, final_trust_bundle_path]:
        ensure_directory(os.path.dirname(p))

    # 1. Load or Generate Account Key
    account_key_path = cfg.account_key_path
    if os.path.exists(account_key_path):
        logger.info(f"Loading account key from {account_key_path}")
        account_key = load_private_key(account_key_path)
    else:
        logger.info(f"Generating new account key ({key_type}) at {account_key_path}")
        account_key = generate_private_key(key_type)
        save_private_key(account_key, account_key_path)

    # 2. Generate Agent Key
    if os.path.exists(agent_key_path):
        logger.info(f"Loading existing agent key from {agent_key_path}")
        agent_key = load_private_key(agent_key_path)
    else:
        logger.info(f"Generating new agent key ({key_type}) at {agent_key_path}")
        agent_key = generate_private_key(key_type)
        save_private_key(agent_key, agent_key_path)

    # 3. Generate CSR
    logger.info(f"Generating CSR for {aic}")
    logger.debug(f"CSR output path: {csr_path}")
    csr_obj = generate_csr(agent_key, aic, csr_path)
    from cryptography.hazmat.primitives import serialization

    csr_pem = csr_obj.public_bytes(serialization.Encoding.PEM)

    # 4. Initialize ACME Client
    client = AcmeClient(cfg.ca_server_url, account_key)

    try:
        # Create Account (if not exists)
        logger.info("Registering ACME account...")
        client.new_account()

        # Create Order
        logger.info(f"Creating certificate order for {aic}...")
        order = client.new_order(aic)

        # Handle Challenges
        _handle_challenges(
            client, order, cfg.challenge_server_url, aic, cfg.challenge_deploy_mock
        )

        # Finalize Order
        logger.info("Finalizing order...")
        order = client.finalize_order(order["finalize"], csr_pem)

        while order["status"] in ["processing", "pending"]:
            logger.debug(f"Order status: {order['status']}, polling...")
            time.sleep(2)
            # Re-fetch order status (using order URL from Location header, but we need to store it)
            # Simplified: assume finalize returns valid or we can poll the order URL
            # In a full implementation, we should poll the order URL.
            # For now, let's assume finalize returns the updated order object or we need a way to get it.
            # The AcmeClient.new_order returns the order object with 'url'.
            resp = client._post(order["url"], None)  # POST-as-GET to poll order
            order = resp.json()
            order["url"] = resp.headers.get(
                "Location", order.get("url")
            )  # Update URL if changed

            if order["status"] == "valid":
                break
            if order["status"] == "invalid":
                raise click.ClickException(f"Order failed: {order.get('error')}")

        # Download Certificate
        if order["status"] == "valid":
            logger.info("Downloading certificate...")
            cert_pem = client.get_certificate(order["certificate"])

            with open(final_cert_path, "wb") as f:
                f.write(cert_pem)
            logger.info(f"Certificate saved to {final_cert_path}")

            # Also update trust bundle
            ctx.invoke(update_trust_bundle, output=final_trust_bundle_path)

    except AcmeError as e:
        logger.error(f"ACME error: {e}")
        if e.detail:
            logger.debug(f"Error detail: {e.detail}")
        raise click.Abort()


@main.command()
@click.option("--aic", "-a", required=True, help="Agent Identity Code")
@click.option(
    "--key-path",
    type=click.Path(dir_okay=False),
    help="Output path for agent private key",
)
@click.option(
    "--cert-path",
    type=click.Path(dir_okay=False),
    help="Output path for certificate chain",
)
@click.option(
    "--trust-bundle-path",
    type=click.Path(dir_okay=False),
    help="Output path for trust bundle",
)
@click.pass_context
def renew_cert(ctx, aic, key_path, cert_path, trust_bundle_path):
    """Renew an existing certificate."""
    # Reuse new_cert logic as renewal is just a new order
    ctx.invoke(
        new_cert,
        aic=aic,
        key_path=key_path,
        cert_path=cert_path,
        trust_bundle_path=trust_bundle_path,
    )


@main.command()
@click.option(
    "--new-key",
    "-n",
    type=click.Path(dir_okay=False),
    help="Path to a pre-generated key file or the destination for an auto-generated key",
)
@click.option(
    "--key-type",
    "-k",
    default="ec",
    type=click.Choice(["ec", "rsa"]),
    help="Key type when auto-generating a new key",
)
@click.option(
    "--backup/--no-backup",
    default=True,
    help="Backup the current account key before replacing it",
)
@click.pass_context
def key_rollover(ctx, new_key, key_type, backup):
    """Rotate the ACME account key pair."""
    cfg = ctx.obj["config"]
    account_key_path = cfg.account_key_path

    if not os.path.exists(account_key_path):
        raise click.ClickException(
            f"Account key not found at {account_key_path}. Create an account first."
        )

    old_key = load_private_key(account_key_path)
    client = AcmeClient(cfg.ca_server_url, old_key)

    logger.info("Retrieving existing ACME account...")
    try:
        client.new_account(only_return_existing=True)
    except AcmeError as exc:
        raise click.ClickException(f"Failed to retrieve account: {exc}")

    new_key_obj = None
    new_key_output_path = None

    if new_key and os.path.exists(new_key):
        if os.path.samefile(new_key, account_key_path):
            raise click.ClickException(
                "The --new-key path points to the current account key. Provide a different file."
            )
        logger.info(f"Loading pre-generated key from {new_key}")
        new_key_obj = load_private_key(new_key)
        new_key_output_path = new_key
    else:
        logger.info(f"Generating new account key ({key_type})")
        new_key_obj = generate_private_key(key_type)
        if new_key:
            new_key_output_path = new_key
        else:
            timestamp = time.strftime("%Y%m%d%H%M%S")
            new_key_output_path = os.path.join(
                os.path.dirname(account_key_path), f"account-new-{timestamp}.key"
            )
        logger.debug(f"New key output path: {new_key_output_path}")

    logger.info("Requesting key rollover from CA server...")
    try:
        client.key_change(new_key_obj)
    except AcmeError as exc:
        raise click.ClickException(f"Key rollover failed: {exc}")

    backup_path = None
    if backup:
        timestamp = time.strftime("%Y%m%d%H%M%S")
        backup_path = f"{account_key_path}.bak-{timestamp}"
        shutil.copy2(account_key_path, backup_path)
        logger.info(f"Old key backed up to {backup_path}")

    save_private_key(new_key_obj, account_key_path)
    logger.info(f"Account key updated at {account_key_path}")

    if new_key_output_path:
        if not os.path.exists(new_key_output_path):
            save_private_key(new_key_obj, new_key_output_path)
            logger.debug(f"New key also saved to {new_key_output_path}")
        elif os.path.samefile(new_key_output_path, account_key_path):
            # Already saved when updating account key path
            pass
        else:
            logger.debug("Reused provided key file")

    if backup_path:
        logger.info("Old key backup retained. Remove it manually if not needed.")

    logger.info("Key rollover completed successfully")


@main.command()
@click.option("--aic", "-a", required=True, help="Agent Identity Code")
@click.option("--reason", "-r", default="unspecified", help="Revocation reason")
@click.pass_context
def revoke_cert(ctx, aic, reason):
    """Revoke a certificate."""
    cfg = ctx.obj["config"]
    cert_path = os.path.join(cfg.certs_dir, f"{aic}.pem")

    if not os.path.exists(cert_path):
        raise click.ClickException(f"Certificate not found at {cert_path}")

    # Load account key
    account_key_path = cfg.account_key_path
    if not os.path.exists(account_key_path):
        raise click.ClickException(f"Account key not found at {account_key_path}")
    account_key = load_private_key(account_key_path)

    client = AcmeClient(cfg.ca_server_url, account_key)

    # Map reason string to code
    reasons = {
        "unspecified": 0,
        "keyCompromise": 1,
        "cACompromise": 2,
        "affiliationChanged": 3,
        "superseded": 4,
        "cessationOfOperation": 5,
    }
    reason_code = reasons.get(reason, 0)

    try:
        with open(cert_path, "rb") as f:
            cert_pem = f.read()

        logger.info(f"Revoking certificate for {aic}...")
        logger.debug(f"Certificate path: {cert_path}")
        logger.debug(f"Revocation reason: {reason} (code={reason_code})")
        client.revoke_cert(cert_pem, reason_code)
        logger.info("Certificate revoked successfully")
    except AcmeError as e:
        logger.error(f"Failed to revoke certificate: {e}")
        if e.detail:
            logger.debug(f"Error detail: {e.detail}")


@main.command()
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False),
    help="Output path for trust bundle",
)
@click.pass_context
def update_trust_bundle(ctx, output):
    """Update the local trust bundle."""
    cfg = ctx.obj["config"]
    url = f"{cfg.ca_server_url}/ca/trust-bundle"
    path = output or cfg.trust_bundle_path

    ensure_directory(os.path.dirname(path))

    logger.info("Downloading trust bundle...")
    logger.debug(f"Trust bundle URL: {url}")
    logger.debug(f"Trust bundle output path: {path}")
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        with open(path, "wb") as f:
            f.write(resp.content)
        logger.info(f"Trust bundle saved to {path}")
    except Exception as e:
        logger.error(f"Failed to update trust bundle: {e}")


@main.command()
@click.option("--output", "-o", help="Output file path")
@click.option(
    "--format",
    "-f",
    default="der",
    type=click.Choice(["der", "pem"]),
    help="CRL format",
)
@click.pass_context
def download_crl(ctx, output, format):
    """Download the Certificate Revocation List (CRL)."""
    cfg = ctx.obj["config"]
    client = AcmeClient(cfg.ca_server_url, None)

    try:
        logger.info(f"Downloading CRL ({format} format)...")
        crl_content = client.download_crl(format=format)

        if output:
            out_path = output
        else:
            ext = "crl" if format == "der" else "pem"
            out_path = os.path.join(cfg.certs_dir, f"ca.{ext}")

        ensure_directory(os.path.dirname(out_path))
        with open(out_path, "wb") as f:
            f.write(crl_content)
        logger.info(f"CRL saved to {out_path}")
    except Exception as e:
        logger.error(f"Failed to download CRL: {e}")


@main.command()
@click.option("--cert", "-c", required=True, help="Certificate file path")
@click.option("--issuer", "-i", required=True, help="Issuer certificate file path")
@click.pass_context
def check_ocsp(ctx, cert, issuer):
    """Check certificate status via OCSP."""
    cfg = ctx.obj["config"]
    client = AcmeClient(cfg.ca_server_url, None)

    try:
        with open(cert, "rb") as f:
            cert_pem = f.read()
        with open(issuer, "rb") as f:
            issuer_pem = f.read()

        logger.info("Checking OCSP status...")
        logger.debug(f"Certificate file: {cert}")
        logger.debug(f"Issuer file: {issuer}")
        resp = client.check_ocsp(cert_pem, issuer_pem)

        logger.info(f"OCSP response status: {resp.response_status}")

        if resp.response_status == ocsp.OCSPResponseStatus.SUCCESSFUL:
            logger.info(f"Certificate status: {resp.certificate_status}")
            if resp.certificate_status == ocsp.OCSPCertStatus.REVOKED:
                logger.info(f"Revocation time: {resp.revocation_time}")
                logger.info(f"Revocation reason: {resp.revocation_reason}")
            elif resp.certificate_status == ocsp.OCSPCertStatus.GOOD:
                logger.info("Certificate is valid (GOOD)")
            elif resp.certificate_status == ocsp.OCSPCertStatus.UNKNOWN:
                logger.warning("Certificate status is UNKNOWN")
    except Exception as e:
        logger.error(f"OCSP check failed: {e}")


if __name__ == "__main__":
    main()
