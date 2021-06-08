"""
This module provides utility functions for consumption
"""
from pathlib import Path
from typing import List, Tuple
import re


def classify_logs_command(log_dir: Path) -> List[Tuple[str, Path]]:
    """
    Classify log files based on used command
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
