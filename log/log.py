"""
Logging module, a thin wrapper around the standard `logging` module,
and designed to be a drop-in replacement for the same.
Just use `import log` instead of `import loggging`.
"""

import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import List, Tuple


import re

# Default filename of the log file.

LOG_FILE_DIR = Path.home() / ".cache"

LOGFILE = LOG_FILE_DIR / os.environ.get("LOGFILE_NAME", "sitar.log")

# Default log record format.
FORMAT = "\t".join(
    (
        "%(asctime)s",
        "%(levelname)s",
        "[%(name)s]",
        "%(filename)s:%(lineno)d",
        "%(funcName)s",
        "%(message)s",
    )
)

# Default date/time format of log records.
DATETIME = "%Y-%m-%d %H:%M:%S.%u"

# Root logger.
ROOT = logging.getLogger()


def configure(
    filename: Path = LOGFILE, level=logging.INFO, format=FORMAT, datefmt=DATETIME
) -> None:
    """
    Configure logging subsystem. This should be called automatically on
    importing this module.
    """
    logging.basicConfig(
        filename=Path(filename),
        filemode="a",
        format=format,
        datefmt=datefmt,
        level=logging.DEBUG,
    )

    # Rotate logs after 20 runs
    handler = logging.handlers.RotatingFileHandler(filename, backupCount=20)
    handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(fmt=format, datefmt=datefmt)
    handler.setFormatter(file_formatter)
    ROOT.addHandler(handler)
    handler.doRollover()

    # Log both to file and console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(fmt="%(levelname)s: %(message)s")
    console_handler.setFormatter(console_formatter)
    ROOT.addHandler(console_handler)


# Ensure logging is configured as soon as this module is imported.

configure()


def set_debug() -> None:
    """
    Sets the log level of the root logger (and all underneath it) to DEBUG.
    """
    ROOT.setLevel(logging.DEBUG)


def cli_arguments() -> None:
    """
    Called to log invocation arguments in CLI mode (e.g. where __name__ == "__main__").
    """
    cli = logging.getLogger("__main__")
    cli.debug("Arguments: %s", " ".join(sys.argv))


def call_arguments() -> None:
    """
    Call to log the invoked function / method and the passed arguments.
    """
    import inspect

    current_frame = inspect.currentframe()
    caller_frame = inspect.getouterframes(current_frame, 2)
    filename = Path(caller_frame[1].filename)
    module_path = ".".join([filename.parent.name, filename.name.replace(".py", "")])
    logger = logging.getLogger(module_path)

    logger.debug(
        "%s.%s(%s)",
        caller_frame[1][0].f_locals.get("self", object()).__class__.__qualname__,
        caller_frame[1][0].f_code.co_name,
        json.dumps(
            {k: str(v) for k, v in caller_frame[1][0].f_locals.items() if k != "self"}
        ),
    )


def classify_logs_command(log_dir: Path) -> List[Tuple[str, Path]]:
    """
    Classify log files based on used command
    """
    # find .log files and rotated log files ending with int e.g ex.log.1
    matched_files = []
    log_files = []
    log_files.extend(log_dir.glob("*.log"))
    log_files.extend(log_dir.glob("*.log.*[1-9]"))
    command_patt = r"(?<=\[command\]=)\w+"
    # Loop through log file , open and read command
    for log_file in log_files:
        with open(log_file, "r") as f:
            log_text = f.read()
            result = re.search(command_patt, log_text)
            if result:
                command = result.group(0)
                matched_files.append((command, log_file))

    # Sort based on command
    matched_files = sorted(matched_files, key=lambda pair: pair[0])
    return matched_files


# Convenience shortcuts.
log = logging.log
debug = logging.debug
info = logging.info
warning = logging.warning
error = logging.error
exception = logging.exception
critical = logging.critical
fatal = logging.fatal
getLogger = logging.getLogger


DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR
CRITICAL = logging.CRITICAL
FATAL = logging.FATAL
