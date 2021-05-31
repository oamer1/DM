""" Script to update Hrefs from a spreadsheet of Hrefs """

import argparse
import csv
import logging
import os
import sys
from pathlib import Path
from typing import Dict

LOGGER = logging.getLogger(__name__)


def get_hrefs_from_xls(fname: str) -> Dict:
    """read in the Excel spreadsheet and store the Hrefs in a dict that is returned"""
    import Spreadsheet_xls

    ss = Spreadsheet_xls.Spreadsheet()
    ss.open_ss(fname)
    ss.set_active_sheet_no(0)
    ss.set_header_key("CORE NAME")
    href_hash = {}
    for href in ss.rows_after_header():
        if "DESIGNSYNC INFORMATION" in href:
            href_hash[href["DESIGNSYNC INFORMATION"]] = href["CORE NAME"]
        elif "DESIGNSYNC VAULT URL" in href:
            url = href["DESIGNSYNC VAULT URL"] + "@" + href["DM VERSION"]
            href_hash[url] = href["CORE NAME"]
    return href_hash


def save_hrefs_to_csv(fname: str, hrefs: Dict) -> None:
    """save the hrefs to a CSV file"""
    rows = [["Url", "Relpath"]]
    for href in hrefs:
        # TODO - what about Trunk?
        url = href["url"] + "@" + href["selector"]
        rows.append([url, href["relpath"]])

    try:
        with open(fname, "w") as csvfile:
            csv.writer(csvfile).writerows(rows)
    except IOError as err:
        LOGGER.warn(f" Cannot write to the CSV file {fname} - {err}")


def get_hrefs_from_csv(fname: str) -> None:
    """read in the hrefs from a CSV file"""
    hrefs = {}
    try:
        with open(fname, "r") as csvfile:
            reader = csv.reader(csvfile, delimiter=",")
            headers = next(reader)
            for row in reader:
                (url, relpath) = row
                hrefs[url] = relpath
    except IOError as err:
        LOGGER.warn(f" Cannot read the CSV file {fname} - {err}")
    return hrefs


def main() -> int:
    """Main routine that is invoked when you run the script"""
    parser = argparse.ArgumentParser(
        description="Script to automatically update Hrefs from a spreadsheet.",
        add_help=True,
        argument_default=None,  # Global argument default
    )
    # TODO - add in support for CSV files
    parser.add_argument("-i", "--input", help="Specify the input CSV file")
    parser.add_argument("-o", "--output", help="Specify the output CSV file")
    parser.add_argument(
        "-d", "--debug", action="store_true", help="enable debug outputs"
    )
    parser.add_argument("-s", "--show", action="store_true", help="Show the Hrefs")
    parser.add_argument(
        "-a",
        "--auto",
        action="store_true",
        help="Automatically update the hrefs (no prompts)",
    )
    parser.add_argument(
        "-x", "--xls", help="Update hrefs provided in an XLS spreadsheet"
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
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    # Hack to work around Dsync symlinks
    path_of_script = Path(__file__).absolute().parent
    sys.path.append(str(path_of_script))

    import Dsync

    import Process

    if args.test:
        import doctest

        doctest.testmod()

    if args.directory:
        start_dir = args.directory
    else:
        start_dir = Path.cwd()

    if "DM_WORKSPACE_NAME" in os.environ:
        LOGGER.error(
            f"This script cannot be run from a DMSH shell. Please run in a different terminal window"
        )
        return 1

    LOGGER.debug(f"start dir = {start_dir}")
    dm = Dsync.Dsync(cwd=start_dir, test_mode=args.test)

    root_dir = Dsync.get_sitr_root_dir(start_dir)
    shrc_project = root_dir / ".shrc.project"
    if shrc_project.exists():
        LOGGER.debug(f"setting source file to be {shrc_project}")
        dm.set_shrc_project(shrc_project)

    dm_shell = Process.Process()
    dm.configure_shell(dm_shell)
    with dm_shell.run_shell():
        hrefs = {}
        if args.xls:
            hrefs = get_hrefs_from_xls(args.xls)
        elif args.input:
            hrefs = get_hrefs_from_csv(args.input)

        print("Waiting for DM shell")
        if not dm_shell.wait_for_shell():
            print("Timeout waiting for DM shell")

        container = dm.stclc_current_module()

        if hrefs:
            print(f"Updating the container {container['url']}")
            for url in hrefs:
                dm.add_href(container["url"], url, hrefs[url], test_flag=True)

            if args.auto or Dsync.prompt_to_continue("Update Hrefs"):
                for url in hrefs:
                    dm.add_href(container["url"], url, hrefs[url])
                if args.auto or Dsync.prompt_to_continue("Populate Updates"):
                    dm.populate(container["modinstname"], force=True)

        if args.show:
            dm.show_hrefs(container["url"])

        if args.output:
            save_hrefs_to_csv(args.output, dm.get_hrefs(container["url"]))

        if args.interactive:
            import IPython  # type: ignore

            IPython.embed()  # jump to ipython shell

    return 0


if __name__ == "__main__":
    sys.exit(main())
