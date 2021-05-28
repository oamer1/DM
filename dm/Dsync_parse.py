#! /pkg/qct/software/python/3.6.0/bin/python
""" Contains the modules and functions or accessing Design Sync
    Examples:
        import dm
"""
import argparse
import datetime
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import log
import dm

LOGGER = log.getLogger(__name__)


def _add_to_kv_list(kv_list, string: str) -> bool:
    """split a string and add words to the kv_list"""
    items = string.split()
    if items:
        kv_list.extend(items)
        return True
    return False


def _kv_list_to_dict(kv_list: List) -> Dict:
    """convert a list of key1, value1, key2, value2, etc to a dictionary"""
    return dict(zip(kv_list[0::2], kv_list[1::2]))


def parse_list_of_list_response(response: str) -> List:
    """parse the response from a dsync command one character at a time and convert it
    to a list of key value dictionaries"""
    brace_level = 0
    item_list = []
    start_idx = 0
    for cur_idx, char in enumerate(response):
        if char == "{":
            if brace_level == 0:
                start_idx = cur_idx + 1
            brace_level += 1
        elif char == "}":
            brace_level -= 1
            if brace_level == 0:
                # item_list.append(parse_list_response(response[start_idx:cur_idx+1]))
                item_list.append(response[start_idx:cur_idx].split())
    return item_list


def parse_list_kv_response(response: str) -> List:
    """parse the response from a dsync command one character at a time and convert it
    to a list of list of key value dictionaries"""
    brace_level = 0
    item_list = []
    start_idx = 0
    for cur_idx, char in enumerate(response):
        if char == "{":
            if brace_level == 0:
                start_idx = cur_idx + 1
            brace_level += 1
        elif char == "}":
            brace_level -= 1
            if brace_level == 0:
                item_list.append(parse_kv_response(response[start_idx : cur_idx + 1]))
    return item_list


def parse_value_response(kv_list: List, value: str) -> Dict:
    """parse the value response from DesignSync, the key must be checked to
    see how to parse the data"""
    key = "" if not kv_list else kv_list[-1]
    if key == "comment" or key == "mtime" or key == "date":
        parse_func = str
    elif key == "objects":
        parse_func = parse_list_kv_response
    elif key == "tag_properties":
        parse_func = parse_list_of_list_response
    else:
        parse_func = parse_kv_response
    return parse_func(value)


def parse_kv_response(response: str) -> Dict:
    """parse the response from a dsync command one character at a time and convert it
    to a dictionary which are assumed to be key value pairs"""
    if not response:
        return {}
    brace_level = 0
    kv_list = []
    start_idx = 0
    end_idx = len(response)
    found_key = False
    for cur_idx, char in enumerate(response):
        if char == "{":
            if brace_level == 0:
                found_key |= _add_to_kv_list(kv_list, response[start_idx:cur_idx])
                start_idx = cur_idx + 1
            brace_level += 1
        elif char == "}":
            brace_level -= 1
            if brace_level == 0:
                kv_list.append(
                    parse_value_response(kv_list, response[start_idx:cur_idx])
                )
                start_idx = cur_idx + 1
        elif char == "\n":
            end_idx = cur_idx
    found_key |= _add_to_kv_list(kv_list, response[start_idx:end_idx])
    if found_key:
        return _kv_list_to_dict(kv_list)
    return kv_list


def get_files(kv_response: Dict) -> List[Dict]:
    """after a command has been parsed, this routine will convert into a list of files"""
    if kv_response.get("type") == "file":
        obj_dict = {"name": kv_response["name"]}
        obj_dict.update(kv_response["props"])
        return [obj_dict]
    files = []
    if kv_response.get("objects"):
        for obj_list in kv_response["objects"]:
            files.extend(get_files(obj_list))
    return files


def format_hrefs(mod: str, submod: str, hrefs: List[Dict]) -> List[Dict]:
    """Format the hrefs for the specified module as records"""
    table = []
    for href in hrefs:
        if href["type"] == "Module":
            row = {
                "module": mod,
                "submodule": href["name"],
                "source_url": href["url"],
                "name": href["name"],
                "relpath": href["relpath"],
                "url": href["url"],
                "selector": href["selector"],
            }

        else:
            # Should NOT happen anyway
            raise ValueError

        if submod and submod != row["submodule"]:
            continue

        if "hrefs" not in href:
            continue

        for sub in href["hrefs"]:
            row = row.copy()
            row.update(
                name=sub["name"],
                relpath=sub["relpath"],
                selector=sub["selector"],
                url=sub["url"],
            )
            table += [row]

    return table


def process_sitr_update_list(self, resp_list: List[str]) -> List:
    """get a list of newly submitted modules that can be integrated"""
    resp_str = " ".join([resp.split("\n")[0] for resp in resp_list])
    # TODO - need to support the all switch with multiple submits
    update_list = {}
    kv_resp = parse_kv_response(f"{resp_str}")
    for url, settings in kv_resp.items():
        (base_url, selector) = url.split("@")
        if re.search(r"v\d\.\d+$", selector):
            root_mod = base_url.split("/")[-1]
            new_item = settings
            new_item["module"] = root_mod
            new_item["date"] = int(settings["date"])
            prev_date = (
                update_list[root_mod]["date"] if root_mod in update_list else 0
            )
            if new_item["date"] > prev_date:
                update_list[root_mod] = new_item
    return update_list

def parse_sitr_modules(resp) -> Dict:
    """return the SITaR modules and their status"""
    modules = {}
    keys = ["selector", "baseline", "relpath", "status"]
    for line in resp.split("\n"):
        if not line.startswith(" "):
            continue
        items = line.split()
        first_item = next(iter(items), "")
        if "%" in first_item:
            modules[first_item[:-2]] = dict(zip(keys, items[1:]))
    return modules

def process_sitr_update_list(resp_list: List[str]) -> List:
    """get a list of newly submitted modules that can be integrated"""
    resp_str = " ".join([resp.split("\n")[0] for resp in resp_list])
    # TODO - need to support the all switch with multiple submits
    update_list = {}
    kv_resp = parse_kv_response(f"{resp_str}")
    for url, settings in kv_resp.items():
        (base_url, selector) = url.split("@")
        if re.search(r"v\d\.\d+$", selector):
            root_mod = base_url.split("/")[-1]
            new_item = settings
            new_item["module"] = root_mod
            new_item["date"] = int(settings["date"])
            prev_date = (
                update_list[root_mod]["date"] if root_mod in update_list else 0
            )
            if new_item["date"] > prev_date:
                update_list[root_mod] = new_item
    return update_list


def main():
    """Main routine that is invoked when you run the script"""
    parser = argparse.ArgumentParser(
        description="Test script for the Dsync class.",
        add_help=True,
        argument_default=None,  # Global argument default
    )
    parser.add_argument(
        "-d", "--debug", action="store_true", help="enable debug outputs"
    )
    parser.add_argument("-D", "--directory", help="Specify the directory to update")
    parser.add_argument(
        "-I", "--interactive", action="store_true", help="enable an interactive session"
    )
    parser.add_argument("-t", "--test", action="store_true", help="run the doc tester")
    parser.add_argument(
        "-T",
        "--test_mode",
        action="store_true",
        help="Run in test mode without actually changing things",
    )
    args = parser.parse_args()
    if args.debug:
        log.set_debug()

    if args.test:
        import doctest

        doctest.testmod()

    if args.interactive:
        import IPython  # type: ignore

        IPython.embed()  # jump to ipython shell


if __name__ == "__main__":
    main()

