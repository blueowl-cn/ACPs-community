import logging
from pathlib import Path
from acps_ca_challenge.config import settings
from acps_ca_challenge.exception import ChallengeNotFoundError, ChallengeStorageError

LOGGER = logging.getLogger("challenge_server")


def _get_challenge_path(agent_aic: str, token: str) -> Path:
    return settings.CHALLENGE_DIR / agent_aic / token


def get_challenge(agent_aic: str, token: str) -> str:
    path = _get_challenge_path(agent_aic, token)
    if not path.is_file():
        raise ChallengeNotFoundError(f"Challenge not found: {agent_aic}/{token}")

    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as e:
        LOGGER.error(f"Failed to read challenge file {path}: {e}")
        raise ChallengeStorageError(f"Failed to read challenge: {e}")


def save_challenge(agent_aic: str, token: str, content: str) -> None:
    path = _get_challenge_path(agent_aic, token)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as e:
        LOGGER.error(f"Failed to write challenge file {path}: {e}")
        raise ChallengeStorageError(f"Failed to save challenge: {e}")


def init_storage():
    try:
        settings.CHALLENGE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        LOGGER.error(
            f"Error creating challenge directory {settings.CHALLENGE_DIR}: {e}"
        )
        raise
