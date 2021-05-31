#! /pkg/qct/software/python/3.6.0/bin/python
""" Contains the modules and functions or accessing Design Sync
    Examples:
        import Dsync
        dm = Dsync.Dsync(cwd='/tmp')
        dm_shell = Process.Process()
        dm.configure_shell(dm_shell)
        with dm_shell.run_shell():
            dm_shell.wait_for_shell()
            dm.stclc_mod_exists("sync://ds-wanip-sec14-chips-2:3065/Projects/MAGNUS_TOP")
"""
import argparse
import datetime
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

import log
import pandas as pd
import tabulate

LOGGER = log.getLogger(__name__)


class Dsync_io(object):
    """Class for accessing Design Sync IO routines
    This class should be used with the Process class (which starts up the stclc
    shell). The methods will send commands to the process and check the
    response.
    Attributes:
        test_mode: when true, do not display anything
    """

    # Methods to initialize the Class
    def __init__(self, test_mode=False) -> None:
        """Initializer for the Dsync_io class"""
        self.table = {}
        self.test_mode = test_mode
        self.fname = None
        self.df = None
        self.resp = []
        self.contents = None

    def display_hrefs(self, hrefs: List[Dict]) -> None:
        """Display the hrefs for the specified URL"""
        headers = ["module", "source_url", "url", "selector", "relpath"]
        self.table = {}
        for header in headers:
            self.table[header] = [href[header] for href in hrefs if "module" in href]

        if not self.test_mode:
            print(tabulate.tabulate(self.table, headers="keys", tablefmt="pretty"))
            print()

    def display_module_hrefs(self, rows: List[str], fname: str = "") -> None:
        """show the hrefs of the modules, or use the top module if not specified"""
        if fname:
            if self.test_mode:
                self.fname = fname
                return

            path = Path(fname)
            df = pd.DataFrame.from_records(rows)[
                [
                    "module",
                    "submodule",
                    "source_url",
                    "name",
                    "relpath",
                    "selector",
                    "url",
                ]
            ]
            if path.suffix == ".csv":
                df.to_csv(fname, index=False)
            elif path.suffix == ".xls" or path.suffix == ".xlsx":
                df.to_excel(fname, index=False)
            else:
                LOGGER.error(f"Unsupported file type ({fname})")

        else:
            self.display_hrefs(rows)

    def read_hrefs(self, fname: str):
        """show the hrefs of the modules, or use the top module if not specified"""
        if self.test_mode:
            return self.df
        path = Path(fname)
        if path.suffix == ".csv":
            df = pd.read_csv(fname)
        elif path.suffix == ".xls" or path.suffix == ".xlsx":
            # TODO - specify a tab?
            df = pd.read_excel(fname)
        else:
            LOGGER.error(f"Unsupported file type ({fname})")
            return None
        return df

    def display_file_versions(self, files: List) -> None:
        headers = ["name", "version"]
        self.table = {}
        for header in headers:
            self.table[header] = [file[header] for file in files]
        if not self.test_mode:
            print(tabulate.tabulate(self.table, headers="keys", tablefmt="pretty"))

    def display_file_locks(self, files: List) -> None:
        headers = ["user", "name", "where"]
        self.table = {}
        for header in headers:
            self.table[header] = [item[header] for item in files["contents"]]
        if not self.test_mode:
            print(tabulate.tabulate(self.table, headers="keys", tablefmt="psql"))

    def display_mod_files(self, files: List[Dict], version: bool = False) -> None:
        """display the list of modified files in a table"""
        if version:
            headers = ["name", "fetchedstate", "mtime"]
        else:
            headers = ["name", "version", "mtime"]
        self.table = {}
        for header in headers:
            self.table[header] = [file[header] for file in files]
        if not self.test_mode:
            print(tabulate.tabulate(self.table, headers="keys", tablefmt="grid"))

    def display_mod_list(self, mod_list: List[Dict]) -> None:
        """Display the detected module updates"""
        # TODO - include date
        # datetime.datetime.fromtimestamp(table['date']).strftime('%m-%d-%Y %H:%M:%S')
        headers = ["module", "tagName", "author", "comment"]
        self.table = {}
        for header in headers:
            self.table[header] = [mod_list[mod][header] for mod in mod_list]
        self.table["date"] = [
            datetime.datetime.fromtimestamp(int(mod_list[mod]["date"])).strftime(
                "%m-%d-%Y %H:%M:%S"
            )
            for mod in mod_list
        ]
        if not self.test_mode:
            print(tabulate.tabulate(self.table, headers="keys", tablefmt="pretty"))

    def showstatus_report(self, report) -> List:
        """Runs showstatus command for each module (or top module if none given)"""
        last_mod = ""
        errors = []
        self.table = defaultdict(list)
        for line in report:
            if "%0" not in line:
                # Report errors at the end
                errors += [line]
                continue
            mod, _, msg = line.partition(": ")
            if mod != last_mod and last_mod != "":
                # Add separators between modules
                self.table["module"] += ["-" * 20]
                self.table["status"] += ["-" * 40]

            self.table["module"] += [
                mod if mod != last_mod else ""
            ]  # don't repeat module on each line
            self.table["status"] += [msg.strip()]
            last_mod = mod

        if not self.test_mode:
            print(tabulate.tabulate(self.table, headers="keys", tablefmt="pretty"))
        return errors

    def make_module_readme(self, path: Path, comment: str) -> Path:
        """make a readme file for the module"""
        readme = path / "README.txt"
        if self.test_mode:
            return readme
        if readme.exists():
            return readme
        readme.write_text(comment)
        return readme

    def prompt_to_continue(self, msg: str = "Continue") -> bool:
        """prompt the user to continue"""
        if self.test_mode:
            return self.resp.pop(0)
        if bool(os.environ.get("FORCE_CONTINUE", 0)) is True:
            return True
        resp = input(f"{msg}? (y/n) ")
        return resp.lower().startswith("y")

    def write_mod_versions(self, mod_list, fname):
        """Write out the module versions for integration"""
        self.contents = [f"{mod}@{mod_list[mod]['tagName']}\n" for mod in mod_list]
        if self.test_mode:
            self.fname = fname
            return
        path = Path(fname)
        path.write_text("".join(self.contents))

    def read_mod_versions(self, fname):
        """Read in the module versions for integration"""
        if not self.test_mode:
            f = Path(fname).resolve()
            if not f.exists():
                LOGGER.error(f"Given --integrate file {f!s} NOT found!")
                return []
            self.contents = f.read_text()
        select_list = [
            item.split("@") for item in self.contents.splitlines() if "@" in item
        ]
        return {
            item[0]: {"module": item[0], "tagName": item[1]} for item in select_list
        }


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

    io = Dsync_io(test_mode=args.test_mode)

    if args.interactive:
        import IPython  # type: ignore

        IPython.embed()  # jump to ipython shell


if __name__ == "__main__":
    main()
