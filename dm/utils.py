"""
This module provides utility functions for consumption
"""
from pathlib import Path
from typing import List, Tuple
import re
import sys


def classify_logs_command(log_dir: Path) -> List[Tuple[str, Path]]:
    """
    Enumerate available log files (logfile_name, logfile_Path)
    """
    # find .log files and rotated log files ending with int e.g ex.log.1
    matched_files = []
    log_files = []
    log_files.extend(log_dir.glob("*.log"))
    log_files.extend(log_dir.glob("*.log.*[1-9]"))
    # catch command along with arguments
    command_patt = r"\[command\]=(.*?)#"
    # Loop through log file , open and read command
    for log_file in log_files:
        with open(log_file, "r") as f:
            log_text = f.read()
            result = re.search(command_patt, log_text)
            if result:
                command = result.group(1).strip()
                matched_files.append((command, log_file))

    # Sort based on command
    matched_files = sorted(matched_files, key=lambda pair: pair[0])
    return matched_files


def ask_string_input(prompt: str) -> str:
    """
    Ask user to string input
    """

    # TODO input validation ?
    while True:
        string = input(prompt)

        if string.lower().strip() in ("quit", "q"):
            sys.exit(0)

        if string:
            break

    return string


def ask_option_number(
    options_number: int, prompt: str = "Enter option number: "
) -> int:
    """
    Given options_number , ask user for input integer
    between 1 and options_number inclusive
    """
    option_index = None
    while option_index not in range(1, options_number + 1):
        try:
            _option = input(prompt)
            option_index = int(_option)
        except ValueError:
            if _option in ["quit", "q"]:
                sys.exit(0)
            else:
                print("Please enter valid integer")
    return option_index - 1
