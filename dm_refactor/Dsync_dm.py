#! /pkg/qct/software/python/3.6.0/bin/python
""" Contains the modules and functions or accessing Design Sync
    Examples:
        import Dsync
        dssc = Dsync.Dsync(cwd='/tmp')
        dm_shell = Process.Process()
        dssc.configure_shell(dm_shell)
        with dm_shell.run_shell():
            dm_shell.wait_for_shell()
            dssc.stclc_mod_exists("sync://ds-wanip-sec14-chips-2:3065/Projects/MAGNUS_TOP")
"""
import argparse
import datetime
from logging import Logger
import os
import re
import smtplib
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import log

LOGGER = log.getLogger(__name__)

import dm



class Dsync_dm():
    """Class for accessing Design Sync
    This class should be used with the Process class (which starts up the stclc
    shell). The methods will send commands to the process and check the
    response.
    Attributes:
        cwd: current working directory for the process
        env: environment variable used for the process
        test_mode: when true, do not run any actual commands
        shrc_project: specify a file to source before starting the process
    """

    # Methods to initialize the Class
    def __init__(
        self,
        env: Dict = None,
        cwd: str = None,
        test_mode: bool = False,
        bsub_mode: bool = False,
        label: str = "",
    ) -> None:
        """Initializer for the Dsync class"""
        self.test_mode = test_mode
        self.env = env if env else {}
        self.cwd = cwd
        self.shrc_project = ""
        self.bsub_mode = bsub_mode
        self.label = label
        self.shell = None
        self.io = None

    ###############################################
    # Basic methods to manipulate data
    ###############################################

    def configure_shell(self, shell: "Process", io = None) -> None:
        """configure the shell for running the stclc shell"""
        shell.prompt = "stcl>"
        if self.bsub_mode:
            executable = "/pkg/icetools/bin/bsub"
            exec_args = " -Ip -q interactive stclc"
        else:
            executable = "/pkg/icetools/bin/stclc"
            exec_args = ""

        shell.command = self.shrc_project + executable + exec_args
        shell.end_cmd = "exit"
        shell.init_timeout = 5000
        shell.timeout = 5000
        shell.cwd = self.cwd
        shell.env = self.env
        self.shell = shell
        self.io = io if io else dm.Dsync_io()

    def set_shrc_project(self, fname: "Path") -> None:
        """set the file to source before starting the process"""
        self.shrc_project = f". {fname}; "

    ###############################################
    # Methods that interact with stclc
    ###############################################
    def dump_dss_logfile_to_log(self):
        """Log where Dsync will log commands."""
        resp = self.shell.run_command("log")
            
        for line in resp.splitlines():
            if "Logfile:" in line:
                LOGGER.debug(line.strip())

    def run_cdws(self):
        """Runs cdws commands returns the response."""
        # TODO - check for errors
        return self.shell.run_command("cdws")

    def stclc_get_hrefs(self, url: str) -> str:
        """call stclc to get the hrefs for a particular url, return the response"""
        return self.shell.run_command(f"showhrefs -rec -format list {url}")

    def stclc_puts_resp(self) -> str:
        """check the resp variable for the output from the prev command"""
        return self.shell.run_command(
            f'if [info exists resp] {{ puts $resp }} else {{ puts "ERROR" }}',
            self.test_mode,
        )

    def stclc_check_out(self, fname: str) -> bool:
        """check out files specified by string"""
        self.shell.stream_command_disp(f"set resp [populate -lock {fname}]", self.test_mode)
        return self.check_resp_error(f"check out of {fname}")

    def stclc_check_in(
        self, files: str, comment: str = "", rec: bool = False, args: str = ""
    ) -> bool:
        """check in files stored in a string"""
        if not comment:
            comment = input("Please provide a comment: ")
        self.shell.stream_command_disp(
            f'ci -new {"-rec" if rec else ""} -comment "{comment}" {files}',
            self.test_mode
        )
        # TODO - how to check if this command passes.
        # return self.check_resp_error(f"check in of {files}")
        return False

    def stclc_populate(
        self, url: str = "", force: bool = False, rec: bool = True, args: str = ""
    ) -> bool:
        """run the populate command, print output, and return any errors"""
        pop_args = f'{"-rec" if rec else ""} {"-force" if force else ""}'
        self.shell.stream_command_disp(f"set resp [populate {pop_args} {url} {args}]", self.test_mode)
        return self.check_resp_error(f"populate {url}")

    def stclc_ls_modules(self, module: str, modified: bool = False, locked: bool = False, unmanaged: bool = False, filt: str = "") -> str:
        """scan for files that are checked out in the specified module"""
        ls_args = f'{"-modified" if modified else ""} {"-locked" if locked else ""} {"-unmanaged" if unmanaged else ""}'
        return self.shell.run_command(
            f"ls -rec -path -format list {ls_args} {filt} {module}"
        )

    def stclc_get_file_status(self, path: str) -> Dict:
        """return the design sync status of a single file"""
        resp = self.shell.run_command(
            f"set resp [ls -report status -format list {path}]", self.test_mode
        )
        #files = parse_kv_response(self.stclc_puts_resp())
        #if not files:
        #    return {}
        #return files[0]
        return self.stclc_puts_resp()

    def stclc_module_contents(self, module: str, tag: str = "", path="") -> str:
        """show the contents of the sitr module associated with the specified tag"""
        args = f'{"-selector" if tag else ""} {tag} {"-path" if path else ""} {path}'
        return self.shell.run_command(
            f"contents -modulecontext {module} -format list {args}"
        )

    def stclc_tag_files(self, tag: str, path: str, args: str = "") -> str:
        """Tag the associated file/path with the specified tag"""
        self.shell.stream_command_disp(f"set resp [tag {args} {tag} {path}]", self.test_mode)
        return self.check_resp_error(f"tag files {path}")

    def stclc_module_locks(self, module: str) -> str:
        """show all of the locks in the specified module"""
        return self.shell.run_command(f"showlocks -format list {module}")

    def stclc_module_info(self, module: str) -> str:
        """show the status of the specific module"""
        return self.shell.run_command(f"showstatus -report script {module}")

    def stclc_module_status(self, module: str) -> str:
        """show the status of the specific module"""
        return self.shell.run_command(
            f"showstatus -report brief -rec -objects {module}"
        )

    # mcache show -format list
    # showhrefs -format list  RF_DIG
    # sitr lookup -report script
    # url exists  sync://ds-blaster-lnx-01:3331/Modules/RF_DIG
    def stclc_mod_exists(self, url: str) -> bool:
        """return true if the specified dsync module exists"""
        resp = self.shell.run_command(f"url exists {url}")
        if resp.lstrip().startswith("1"):
            return True
        return False

    def stclc_current_module(self) -> str:
        """return the module for the current working directory"""
        #resp = parse_kv_response(self.shell.run_command(f"showmods -format list"))
        #return resp[-1]
        return self.shell.run_command(f"showmods -format list")

    def stclc_make_mod(self, url: str, desc: str) -> bool:
        """make the specified design sync module"""
        if self.stclc_mod_exists(url):
            LOGGER.warn(f"The DSync module ({url}) already esists")
        else:
            resp = self.shell.stream_command_disp(f'mkmod {url} -comment "{desc}"', self.test_mode)
            if self.stclc_mod_exists(f"{url}"):
                return False
            LOGGER.error(f"The module {url} was not created")
        return True

    def stclc_add_mod(self, container: str, module: str, relpath: str) -> None:
        """add the dsync module to the specified container"""
        resp = self.shell.run_command(
            f"addhref {container} {module} -relpath {relpath}", self.test_mode
        )
        print(resp)

    def stclc_rm_mod(self, container: str, name: str) -> None:
        """remove the dsync module to the specified container"""
        # FIXME: BROKEN - copy/pasted from above
        resp = self.shell.run_command(f"rmhref {container} {name}", self.test_mode)
        print(resp)

    def stclc_compare(self, args: str = "", args2: str = "") -> None:
        """run the compare command"""
        self.shell.stream_command_disp(f"compare {args} {args2}", self.test_mode)

    def stclc_get_branch(self) -> str:
        """Returns the branch we're on, based on SYNC_DEVAREA_TOP"""
        resp = self.shell.run_command("url tags -btags $env(SYNC_DEVAREA_TOP)")
        if resp:
            branch = resp.strip().splitlines()[0].strip()
            return branch
        return ""

    def stclc_get_url_root(self, module: str = "") -> str:
        """Returns the vault of the top module, based on SYNC_DEVAREA_TOP"""
        if not module:
            module = "$env(SYNC_DEVAREA_TOP)"
        return self.shell.run_command(f"url vault {module}")

    def stclc_sitr_lookup(self, mod: str = "") -> str:
        """call stclc to do a sitr lookup to find new submits and return the response"""
        return self.shell.run_command(f"sitr lookup -report script {mod}")

    def stclc_sitr_status(self) -> str:
        """run the sitr status command to show the status of the workspace"""
        return self.shell.run_command(f"sitr status")

    def stclc_update_module(self, module: str, config: str = "") -> bool:
        """update the specified module with the config/selector"""
        args = f'{"-config" if config else ""} {config}'
        self.shell.stream_command_disp(f"set resp [sitr update -config {config} {module}]", self.test_mode)
        resp = self.stclc_puts_resp()
        if resp:
            LOGGER.error(f"sitr update - {resp}")
            return True
        return False

    def stclc_populate_workspace(self, force: bool = False) -> bool:
        """populate the sitr workspace"""
        self.shell.stream_command_disp(
            f'set resp [sitr pop -skiplock {"-force" if force else ""}]',
            self.test_mode
        )
        resp = self.stclc_puts_resp()
        if resp:
            LOGGER.error(f"sitr pop - {resp}")
            return True
        return False

    def stclc_make_sitr_mod(self, name: str, desc: str, no_cache: bool = False) -> None:
        """make the specified SITaR module"""
        args = " -nomcache" if no_cache else ""
        if self.stclc_mod_exists(name):
            LOGGER.warn(f"The SITaR module ({name}) already esists")
        else:
            resp = self.shell.run_command(
                f'sitr mkmod -name {name} -comment "{desc}" {args}', self.test_mode
            )
            print(resp)

    def stclc_add_sitr_mod(self, module: str, release: str, relpath: str = "") -> bool:
        """add the sitr module to the root module"""
        args = f'{"-relpath" if relpath else ""} {relpath}'
        self.shell.stream_command_disp(f"set resp [sitr select {module}@{release} {args}]", self.test_mode)
        resp = self.stclc_puts_resp()
        if resp:
            LOGGER.error(f"sitr select {resp}")
            return True
        return False

    def stclc_submit_module(
        self, modules: List[str], comment: str, skipcheck: bool = False
    ) -> List[Dict]:
        """submit the specified modules"""

        errors = {}
        vers = {}
        args = f'{"-skipcheck" if skipcheck else ""}'
        for mod in modules:
            resp = self.shell.run_command(
                f'sitr submit -force -comment "{comment}" {args} {mod}'
            )

            if resp:
                errors[mod] = {'resp': resp, 'vers': resp.partition("Tagging:")[-1]}

        return errors

    def stclc_integrate(self, nopop: bool = False) -> str:
        """run the sitr integrate command"""
        self.shell.stream_command_disp(
            f'set resp [sitr integrate -noprompt {"-nopop" if nopop else ""}]',
            self.test_mode
        )
        return self.stclc_puts_resp()

    def stclc_sitr_release(
        self,
        comment: str,
        skip_check: bool = False,
        on_server: bool = False
    ) -> str:
        """run the sitr release command"""
        args = f'{"-skipcheck" if skip_check else ""} {"-_fromserver" if on_server else ""}'
        self.shell.stream_command_disp(f'set resp [sitr release -comment "{comment}" {args}]', self.test_mode)
        return self.stclc_puts_resp()

    def stclc_create_branch(self, url: str, version: str, comment: str) -> bool:
        self.shell.stream_command_disp(
            f'set resp [sitr mkbranch -comment "{comment}" {version} {url}]',
            self.test_mode
        )
        resp = self.stclc_puts_resp()
        if resp:
            LOGGER.error(f"create branch {resp}")
            return True
        return False

    def check_resp_error(self, msg: str) -> bool:
        """check the response from a previous command and return True if there is an error"""
        resp = self.stclc_puts_resp()
        if resp == "ERROR":
            LOGGER.error(f"{msg}")
            return True
        status = re.findall(r'{[^}]*}', resp)
        print(status)
        if len(status) != 2:
            LOGGER.error(f"{msg}")
            return True
        if status[1] != "{}":
            LOGGER.error(f"{msg} - {' '.join(status[1])}")
            return True
        return False

    ###############################################
    # Basic calls to the STCLC object
    ###############################################

    def dssc_current_module(self) -> str:
        """return the module for the current working directory"""
        resp = self.stclc_current_module()
        if resp:
            kv = dm.parse_kv_response(resp)
            return kv[-1]
        return None

    def dssc_get_hrefs(self, url: str) -> List[Dict]:
        """return a list of the different hrefs, each item is a dict with attributes"""
        return dm.parse_kv_response(self.stclc_get_hrefs(url))

    def dssc_get_root_url(
        self, module: str = "", branch: str = "", version: str = ""
    ) -> str:
        """Create a branch of the specified module (will be top if not specified)"""
        root = self.stclc_get_url_root(module)
        if branch:
            return f"{root}@{branch}:{version}"
        elif version:
            return f"{root}\;{version}"
        else:
            return root

    def dssc_pop_modules(self, modules: List[str] = (), force: bool = False) -> None:
        """populate the list of SITaR modules"""
        status = False
        if modules:
            mod_list = " ".join(modules)
            LOGGER.info(f"Populating {mod_list}")
            status = self.stclc_populate(mod_list, force=force)
        return status

    def dssc_checkin_module(self, modules: List[str], comment: str) -> bool:
        """check in the specified design sync modules"""
        if modules:
            mod_list = " ".join(modules)
            LOGGER.info(f"Populating {mod_list}")
            return self.stclc_check_in(mod_list, comment, rec=True)
        return False

    def dssc_ls_modules(self, module: str, modified: bool = False, locked: bool = False, unmanaged: bool = False, filt: str = "") -> List[Dict]:
        """get a list of files that are checked out in the specified module"""
        resp = self.stclc_ls_modules(module, modified, locked, unmanaged, filt)
        if not resp.strip().startswith('{'):
            return []
        resp = dm.parse_kv_response(resp)
        if resp:
            return dm.get_files(resp[0])
        return []

    def dssc_show_locks(self, modules: List[str]) -> None:
        """Display the files that are locked in the list of modules"""
        for mod in modules:
            print(f"Scanning {mod}")
            resp = self.stclc_module_locks(mod)
            parsed = dm.parse_kv_response(resp)
            if not parsed or not "contents" in parsed[0]:
                print(f"No checkouts")
                continue
            self.io.display_file_locks(parsed[0])

    def dssc_vhistory(self, modules: List[str]) -> None:
        """runs vhistory for modules"""
        for mod in modules:
            self.shell.run_output(f"vhistory {mod}")

    def dssc_show_checkouts(self, modules: List[str]) -> None:
        """Display a list of the files checked out in the specified modules"""
        for mod in modules:
            print(f"Scanning {mod}")
            files = self.dssc_ls_modules(mod, locked=True)
            if not files:
                print(f"No checkouts")
                continue
            self.io.display_mod_files(files)

    def dssc_show_unmanaged(self, sitr_mods: List[Dict], modules: List[str]) -> None:
        """check the unmanaged files in the module and display the files"""
        for mod in modules:
            print(f"Scanning {mod}")
            path = sitr_mods[mod]["relpath"]
            files = self.dssc_ls_modules(mod, unmanaged=True)
            if files:
                LOGGER.warn(f"The module {mod} has the following unmanaged files")
                self.io.display_mod_files(files)
                continue

    ###############################################
    # Compound calls to the STCLC object
    ###############################################

    def dssc_show_module_hrefs(
        self, modules: List[str], submodule: str, fname: str = ""
    ) -> None:
        """show the hrefs of the modules, or use the top module if not specified"""
        if not modules:
            modules = [os.environ["SYNC_DEVAREA_TOP"]]

        rows = []
        for mod in modules:
            rows += dm.format_hrefs(mod, submodule, self.dssc_get_hrefs(mod))

        self.io.display_module_hrefs(rows, fname)

    def dssc_update_hrefs(self, submodule: str, fname: str) -> int:
        """show the hrefs of the modules, or use the top module if not specified"""
        df = self.io.read_hrefs(fname)

        for container in df["submodule"].unique():
            if submodule and container != submodule:
                continue
            container_hrefs = self.dssc_get_hrefs(container)
            updates = []
            for index, href in df[df["submodule"] == container].iterrows():
                if self.dssc_add_href(
                    container,
                    container_hrefs,
                    href["url"],
                    href["relpath"],
                    href["selector"],
                    test_flag=True,
                ):
                    updates.append(href)
            if not updates:
                print(f"No Hrefs to update for {container}")
                continue
            if self.io.prompt_to_continue("Update Hrefs"):
                for href in updates:
                    self.dssc_add_href(
                        container,
                        container_hrefs,
                        href["url"],
                        href["relpath"],
                        href["selector"],
                    )
                if self.io.prompt_to_continue("Populate Updates"):
                    self.stclc_populate(container, force=True)

    def dssc_add_href(
        self,
        container: str,
        hrefs: List[Dict],
        url: str,
        relpath: str,
        selector: str = "",
        test_flag: bool = False,
    ) -> bool:
        """add the href to the specific container"""
        if selector:
            full_url = f"{url}@{selector}"
        else:
            full_url = f"{url}"
        if not self.stclc_mod_exists(f"{full_url}"):
            LOGGER.warn(f"The Href {full_url} does not exist")
            return False
        for href in hrefs:
            if url == href["url"]:
                if selector == href["selector"]:
                    # LOGGER.warn(f"The Href {href['url']}@{href['selector']} is already present")
                    return False
                elif test_flag:
                    LOGGER.info(
                        f"Updating the Href {href['url']} selector from {href['selector']} to {selector if selector else 'Trunk:'}"
                    )
                else:
                    self.stclc_rm_mod(container, href["name"])
            elif relpath == href["relpath"]:
                if test_flag:
                    LOGGER.info(
                        f"Updating the Href at {href['relpath']} from {href['url']} to {url}"
                    )
                else:
                    self.stclc_rm_mod(container, href["name"])
        if test_flag:
            LOGGER.info(f"Adding the new Href {full_url}")
        else:
            self.stclc_add_mod(container, full_url, relpath)
        return True

    def __repr__(self) -> str:
        """Return the string representation of the object"""
        return f"{type(self).__name__}(label='{self.label}')"


def main():
    """Main routine that is invoked when you run the script"""
    parser = argparse.ArgumentParser(
        description="Test script for the Dsync class.",
        add_help=True,
        argument_default=None,  # Global argument default
    )
    parser.add_argument("-i", "--input", help="Specify the input CSV file")
    parser.add_argument("-o", "--output", help="Specify the output CSV file")
    parser.add_argument(
        "-d", "--debug", action="store_true", help="enable debug outputs"
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
        log.set_debug()
    # Hack to work around Dsync symlinks
    #path_of_script = Path(__file__).absolute().parent
    #sys.path.append(str(path_of_script))
    #from Spreadsheet_if import Spreadsheet_xls

    #ss = Spreadsheet_xls()
    #if args.xls:
    #    ss.open_ss(args.xls)
    #    ss.set_active_sheet_no(0)
    #    ss.set_header_key("CORE NAME")
    if args.test:
        import doctest

        doctest.testmod()
    if args.directory:
        start_dir = args.directory
    else:
        start_dir = Path.cwd()
    print(f"start dir = {start_dir}")
    dssc = Dsync_dm(cwd=start_dir, test_mode=args.test)
    dm_shell = dm.Process()
    dssc.configure_shell(dm_shell)
    with dm_shell.run_shell():
        print("Waiting for DM shell")
        if not dm_shell.wait_for_shell():
            print("Timeout waiting for DM shell")
        if args.interactive:
            import IPython  # type: ignore

            IPython.embed()  # jump to ipython shell


if __name__ == "__main__":
    main()

