#!/usr/bin/env python3
"""Simple HTTP-01 challenge server for ACME testing.

Exposes endpoints to set, fetch, list, and delete HTTP-01 challenge responses.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Iterable, Tuple
from urllib.parse import unquote, urlparse

LOGGER = logging.getLogger("challenge_server")


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    challenge_dir: Path
    api_base_path: str
    challenge_dir_display: str

    @property
    def normalized_base_path(self) -> str:
        base = self.api_base_path.rstrip("/")
        return base if base.startswith("/") else f"/{base}"


class ChallengeRequestHandler(BaseHTTPRequestHandler):
    """Request handler serving challenge endpoints."""

    server_version = "ChallengeHTTP/1.0"
    sys_version = ""

    def __init__(self, *args, config: ServerConfig, **kwargs):
        self._config = config
        super().__init__(*args, **kwargs)

    # BaseHTTPRequestHandler overrides -------------------------------------------------
    def log_message(self, fmt: str, *args: object) -> None:  # noqa: D401 - reduce noise
        LOGGER.debug("%s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:  # noqa: D401 - HTTP verb handler
        parsed = urlparse(self.path)
        if parsed.path == "/status":
            self._handle_status()
            return

        if parsed.path == "/challenges":
            self._handle_list_challenges()
            return

        if self._is_challenge_path(parsed.path):
            agent_id, token = self._extract_agent_and_token(parsed.path)
            if agent_id is None:
                self._send_text(HTTPStatus.BAD_REQUEST, "Invalid path")
                return
            payload = self._read_challenge(agent_id, token)
            if payload is None:
                self._send_text(HTTPStatus.NOT_FOUND, "Challenge not found")
                return
            self._send_text(HTTPStatus.OK, payload)
            LOGGER.info("Served challenge response for %s/%s", agent_id, token)
            return

        self._send_text(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:  # noqa: D401 - HTTP verb handler
        parsed = urlparse(self.path)
        if not self._is_challenge_path(parsed.path):
            self._send_text(HTTPStatus.NOT_FOUND, "Not found")
            return

        agent_id, token = self._extract_agent_and_token(parsed.path)
        if agent_id is None:
            self._send_text(HTTPStatus.BAD_REQUEST, "Invalid path")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(content_length).decode("utf-8")
        if not self._write_challenge(agent_id, token, payload):
            self._send_text(HTTPStatus.INTERNAL_SERVER_ERROR, "Failed to set challenge")
            return

        LOGGER.info("Stored challenge response for %s/%s", agent_id, token)
        self._send_text(HTTPStatus.OK, "Challenge set successfully")

    def do_DELETE(self) -> None:  # noqa: D401 - HTTP verb handler
        parsed = urlparse(self.path)
        if not self._is_challenge_path(parsed.path):
            self._send_text(HTTPStatus.NOT_FOUND, "Not found")
            return

        agent_id, token = self._extract_agent_and_token(parsed.path)
        if agent_id is None:
            self._send_text(HTTPStatus.BAD_REQUEST, "Invalid path")
            return

        deleted = self._delete_challenge(agent_id, token)
        if not deleted:
            self._send_text(HTTPStatus.NOT_FOUND, "Challenge not found")
            return

        LOGGER.info("Deleted challenge response for %s/%s", agent_id, token)
        self._send_text(HTTPStatus.OK, "Challenge deleted successfully")

    # Challenge helpers ----------------------------------------------------------------
    def _is_challenge_path(self, path: str) -> bool:
        agent_token = self._extract_agent_and_token(path)
        return agent_token[0] is not None

    def _extract_agent_and_token(self, path: str) -> Tuple[str | None, str | None]:
        base = self._config.normalized_base_path
        if base == "/":
            relative = path.lstrip("/")
        else:
            if not path.startswith(base):
                return None, None
            relative = path[len(base) :].lstrip("/")

        parts = relative.split("/") if relative else []
        if len(parts) != 2:
            return None, None

        agent_id_decoded = unquote(parts[0])
        token_decoded = unquote(parts[1])
        if not (
            self._is_safe_component(agent_id_decoded)
            and self._is_safe_component(token_decoded)
        ):
            return None, None

        return agent_id_decoded, token_decoded

    @staticmethod
    def _is_safe_component(component: str) -> bool:
        return (
            component != ""
            and ".." not in component
            and "/" not in component
            and "\\" not in component
        )

    def _challenge_path(self, agent_id: str, token: str) -> Path:
        return self._config.challenge_dir / agent_id / token

    def _read_challenge(self, agent_id: str, token: str) -> str | None:
        challenge_file = self._challenge_path(agent_id, token)
        if not challenge_file.is_file():
            return None
        try:
            return challenge_file.read_text(encoding="utf-8")
        except OSError as exc:
            LOGGER.error("Failed to read challenge %s/%s: %s", agent_id, token, exc)
            return None

    def _write_challenge(self, agent_id: str, token: str, payload: str) -> bool:
        challenge_file = self._challenge_path(agent_id, token)
        try:
            challenge_file.parent.mkdir(parents=True, exist_ok=True)
            challenge_file.write_text(payload, encoding="utf-8")
            return True
        except OSError as exc:
            LOGGER.error("Failed to write challenge %s/%s: %s", agent_id, token, exc)
            return False

    def _delete_challenge(self, agent_id: str, token: str) -> bool:
        challenge_file = self._challenge_path(agent_id, token)
        if not challenge_file.exists():
            return False
        challenge_file.unlink(missing_ok=True)
        try:
            parent = challenge_file.parent
            if not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass
        return True

    # Endpoint handlers ----------------------------------------------------------------
    def _handle_status(self) -> None:
        payload = {
            "server": "Agent HTTP-01 Challenge Server",
            "status": "running",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "host": self._config.host,
            "port": self._config.port,
            "api_base_path": self._config.normalized_base_path,
            "challenge_dir": self._config.challenge_dir_display,
            "challenges_count": sum(
                1 for _ in iter_challenge_files(self._config.challenge_dir)
            ),
        }
        self._send_json(HTTPStatus.OK, payload)

    def _handle_list_challenges(self) -> None:
        challenges = [
            str(path.relative_to(self._config.challenge_dir))
            for path in sorted(iter_challenge_files(self._config.challenge_dir))
        ]
        self._send_json(HTTPStatus.OK, challenges)

    # Response helpers -----------------------------------------------------------------
    def _send_json(self, status: HTTPStatus, data: object) -> None:
        body = json.dumps(data, ensure_ascii=False)
        encoded = body.encode("utf-8")
        self.send_response(status.value, status.phrase)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)

    def _send_text(self, status: HTTPStatus, message: str) -> None:
        encoded = message.encode("utf-8")
        self.send_response(status.value, status.phrase)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)


def iter_challenge_files(challenge_dir: Path) -> Iterable[Path]:
    if not challenge_dir.is_dir():
        return ()
    return (path for path in challenge_dir.rglob("*") if path.is_file())


def build_handler(
    config: ServerConfig,
) -> Callable[[tuple, tuple, ThreadingHTTPServer], ChallengeRequestHandler]:
    def factory(*args, **kwargs):
        kwargs.setdefault("config", config)
        return ChallengeRequestHandler(*args, **kwargs)

    return factory  # type: ignore[return-value]


def parse_args(argv: list[str]) -> ServerConfig:
    parser = argparse.ArgumentParser(description="Agent HTTP-01 challenge server")
    parser.add_argument(
        "--host",
        default=os.environ.get("HOST", "0.0.0.0"),
        help="Host to bind (default: %(default)s)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8004")),
        help="Port to listen on (default: %(default)s)",
    )
    parser.add_argument(
        "--challenge-dir",
        default=os.environ.get("CHALLENGE_DIR", "./challenges"),
        help="Directory used to store challenge files (default: %(default)s)",
    )
    parser.add_argument(
        "--api-base-path",
        default=os.environ.get("API_BASE_PATH", "/acps-atr-v1"),
        help="Base path for challenge API endpoints (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    challenge_dir_input = Path(args.challenge_dir).expanduser()
    challenge_dir = (
        challenge_dir_input
        if challenge_dir_input.is_absolute()
        else (Path.cwd() / challenge_dir_input)
    ).resolve()
    challenge_dir.mkdir(parents=True, exist_ok=True)

    config = ServerConfig(
        host=args.host,
        port=args.port,
        challenge_dir=challenge_dir,
        api_base_path=args.api_base_path,
        challenge_dir_display=args.challenge_dir,
    )
    return config


def configure_logging() -> None:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(levelname)s] %(asctime)s %(message)s")
    handler.setFormatter(formatter)
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)


def run(config: ServerConfig) -> None:
    configure_logging()
    request_handler = build_handler(config)
    httpd = ThreadingHTTPServer((config.host, config.port), request_handler)
    httpd.daemon_threads = True

    LOGGER.info("Challenge server listening on http://%s:%d", config.host, config.port)
    LOGGER.info("API base path: %s", config.normalized_base_path)
    LOGGER.info("Challenge directory: %s", config.challenge_dir)

    def shutdown(signum: int, _frame: object) -> None:
        LOGGER.info("Received signal %s. Shutting down...", signum)
        httpd.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        shutdown(signal.SIGINT, None)
    finally:
        httpd.server_close()
        LOGGER.info("Server stopped.")


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv or sys.argv[1:])
    run(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
