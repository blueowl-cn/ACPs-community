import os
import sys
import logging


class CliFormatter(logging.Formatter):
    """Custom formatter for CLI output.

    INFO messages appear as clean text for normal users.
    DEBUG messages are indented with [DEBUG] prefix for developers.
    WARNING/ERROR messages are prefixed with their level.
    """

    def format(self, record):
        msg = record.getMessage()
        if record.levelno == logging.DEBUG:
            return f"  [DEBUG] {msg}"
        elif record.levelno == logging.WARNING:
            return f"[WARNING] {msg}"
        elif record.levelno >= logging.ERROR:
            return f"[ERROR] {msg}"
        return msg


def ensure_directory(path):
    if not os.path.exists(path):
        os.makedirs(path, mode=0o755)


def setup_logging(verbose=False):
    level = logging.DEBUG if verbose else logging.INFO

    pkg_logger = logging.getLogger("acps_ca_client")
    pkg_logger.setLevel(level)
    pkg_logger.handlers.clear()

    formatter = CliFormatter()

    # INFO and DEBUG go to stdout
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)
    stdout_handler.addFilter(lambda record: record.levelno < logging.WARNING)
    stdout_handler.setFormatter(formatter)

    # WARNING and above go to stderr
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(formatter)

    pkg_logger.addHandler(stdout_handler)
    pkg_logger.addHandler(stderr_handler)
    pkg_logger.propagate = False

    # Suppress noisy third-party loggers in verbose mode
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
