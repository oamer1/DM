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
from logging import Logger
import os
import re
import smtplib
import sys
import getpass
from collections import defaultdict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from textwrap import dedent
from typing import Dict, List, Tuple
from jinja2 import FileSystemLoader, Environment, Markup


import tabulate
import Process
import pandas as pd
from lxml.etree import ElementTree as ET

try:
    import log

    LOGGER = log.getLogger(__name__)
except ImportError:
    import logging

    LOGGER = logging.getLogger(__name__)
try:
    import dm
except ImportError:
    import Process

#LOGGER = log.getLogger(__name__)


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


def get_sitr_proj_info(chip_name: str, chip_version: str) -> Tuple:
    """get the project name and container name for a SITaR project"""
    project_name = chip_name + "_" + chip_version
    container_name = chip_name.upper()
    return (project_name, container_name)


def get_sitr_dev_info(base_path: "Path", project_name: str) -> Tuple:
    """get the development dir and development name"""
    development_dir = base_path / project_name.lower()
    development_name = project_name.upper()
    return (development_dir, development_name)


def get_sitr_config_root(development_dir: "Path", config_name: str) -> "Path":
    """get the config root directory for SITaR"""
    config_root = development_dir / "DesignSync" / "Settings" / config_name
    return config_root


def get_sitr_root_dir(dir: str = "") -> "Path":
    """Check the environment variables for the sitar workspace or search"""
    if "PROJ_USER_WORK" in os.environ:
        return Path(os.environ["PROJ_USER_WORK"])
    elif "SYNC_DEVAREA_DIR" in os.environ:
        return Path(os.environ["SYNC_DEVAREA_DIR"])
    elif "DSGN_PROJ" in os.environ:
        return Path(os.environ["DSGN_PROJ"]).parent
    return find_sitr_root_dir(dir)


def find_sitr_root_dir(dir: str = "") -> "Path":
    """Try to find the root SITaR workspace directory"""
    if dir:
        path = Path(dir)
    else:
        path = Path.cwd()
    while path.parents and not Path(path / ".cshrc.project").exists():
        path = path.parent
    return path


def prompt_to_continue(msg: str = "Continue") -> bool:
    """prompt the user to continue"""
    if bool(os.environ.get("FORCE_CONTINUE", 0)) is True:
        return True
    resp = input(f"{msg}? (y/n) ")
    return resp.lower().startswith("y")


class Dsync(object):
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
    ) -> None:
        """Initializer for the Dsync class"""
        self.test_mode = test_mode
        self.env = env if env else {}
        self.cwd = cwd
        self.shrc_project = ""
        self.bsub_mode = bsub_mode
        self.workspace_type = "Design"

    def set_shrc_project(self, fname: "Path") -> None:
        """set the file to source before starting the process"""
        self.shrc_project = f". {fname}; "

    def configure_shell(self, shell: "Process") -> None:
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

    ###############################################
    # Methods that interact with stclc
    ###############################################
    def stclc_set_sitr_alias(self, new_alias: str) -> None:
        """Change the sitr alias with the new value"""
        self.stream_command(f"set ::sitr::GoldenAlias {new_alias}")

    def stclc_get_hrefs(self, url: str) -> str:
        """call stclc to get the hrefs for a particular url, return the response"""
        return self.shell.run_command(f"showhrefs -rec -format list {url}")

    def stclc_sitr_lookup(self, mod: str = "") -> str:
        """call stclc to do a sitr lookup to find new submits and return the response"""
        return self.shell.run_command(f"sitr lookup -report script {mod}")

 

    def stclc_check_resp_error(self, msg: str) -> bool:
        """check the response from a previous command and return True if there is an error"""
        resp = self.stclc_puts_resp()
        print(f"resp = {resp} for {msg}.")
        if resp == "ERROR":
            LOGGER.error(f"{msg}")
            return True
        status = parse_list_of_list_response(resp)
        if len(status[1]) > 0:
            LOGGER.error(f"{msg} - {' '.join(status[1])}")
            return True
        return False

    def stclc_check_out(self, fname: str) -> bool:
        """check out files specified by string"""
        self.stream_command(f"set resp [populate -lock {fname}]")
        return self.stclc_check_resp_error(f"check out of {fname}")

    def stclc_check_in(
        self, files: str, comment: str = "", rec: bool = False, args: str = ""
    ) -> bool:
        """check in files stored in a string"""
        if not comment:
            comment = input("Please provide a comment: ")
        self.stream_command(
            f'ci -new {"-rec" if rec else ""} -comment "{comment}" {files}'
        )
        # TODO - how to check if this command passes.
        # return self.stclc_check_resp_error(f"check in of {files}")
        return False

    def stclc_populate(
        self, url: str = "", force: bool = False, rec: bool = True, args: str = ""
    ) -> bool:
        """run the populate command, print output, and return any errors"""
        pop_args = f'{"-rec" if rec else ""} {"-force" if force else ""}'
        self.stream_command(f"set resp [populate -rec {pop_args} {url} {args}]")
        return self.stclc_check_resp_error(f"populate {url}")

    def stclc_module_checkouts(self, module: str, filter: str = "") -> str:
        """scan for files that are checked out in the specified module"""
        resp = self.shell.run_command(
            f"set resp [ls -rec -workspace -locked -path -format list {filter} {module}]"
        )
        return self.stclc_puts_resp()

    def stclc_get_file_status(self, path: str) -> Dict:
        """return the design sync status of a single file"""
        resp = self.shell.run_command(
            f"set resp [ls -report status -format list {path}]", self.test_mode
        )
        files = parse_kv_response(self.stclc_puts_resp())
        if not files:
            return {}
        return files[0]

    def stclc_module_modified(self, module: str, filter: str = "") -> str:
        """scan for files that are modified in the specified module"""
        resp = self.shell.run_command(
            f"set resp [ls -rec -modified -path -format list {filter} {module}]"
        )
        LOGGER.debug(f"show modified = {resp}")
        return self.stclc_puts_resp()

    def stclc_unmanaged(self, path: str, filter: str = "") -> str:
        """scan for files that are checked out in the specified module"""
        resp = self.shell.run_command(
            f"set resp [ls -unmanaged -rec -path -format list {filter} {path}]"
        )
        return self.stclc_puts_resp()

    def stclc_module_contents(self, module: str, tag: str = "", path="") -> str:
        """show the contents of the sitr module associated with the specified tag"""
        args = f'{"-selector" if tag else ""} {tag} {"-path" if path else ""} {path}'
        return self.shell.run_command(
            f"contents -modulecontext {module} -format list {args}"
        )

    def stclc_tag_files(self, tag: str, path: str, args: str = "") -> str:
        """Tag the associated file/path with the specified tag"""
        self.stream_command(f"set resp [tag {args} {tag} {path}]")
        return self.stclc_check_resp_error(f"tag files {path}")

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

    def stclc_sitr_status(self) -> str:
        """run the sitr status command to show the status of the workspace"""
        return self.shell.run_command(f"sitr status")

    def stclc_update_module(self, module: str, config: str = "") -> str:
        """update the specified module with the config/selector"""
        args = f'{"-config" if config else ""} {config}'
        self.stream_command(f"set resp [sitr update -config {config} {module}]")
        resp = self.stclc_puts_resp()
        if resp:
            LOGGER.error(f"sitr update - {resp}")
            return True
        return False

    def stclc_populate_workspace(self, force: bool = False) -> bool:
        """populate the sitr workspace"""
        self.stream_command(
            f'set resp [sitr pop -skiplock {"-force" if force else ""}]'
        )
        resp = self.stclc_puts_resp()
        if resp:
            LOGGER.error(f"sitr pop - {resp}")
            return True
        return False

    # mcache show -format list
    # showhrefs -format list  RF_DIG
    # sitr lookup -report script
    # url exists  sync://ds-blaster-lnx-01:3331/Modules/RF_DIG
    def stclc_mod_exists(self, url: str) -> bool:
        """return true if the specified dsync module exists"""
        resp = self.shell.run_command(f"url exists {url}")
        # if resp.split()[0] == '1':
        if resp.lstrip().startswith("1"):
            return True
        return False

    def stclc_current_module(self) -> str:
        """return the module for the current working directory"""
        resp = parse_kv_response(self.shell.run_command(f"showmods -format list"))
        return resp[-1]

    def stclc_make_mod(self, url: str, desc: str) -> bool:
        """make the specified design sync module"""
        if self.stclc_mod_exists(url):
            LOGGER.warn(f"The DSync module ({url}) already esists")
        else:
            resp = self.stream_command(f'mkmod {url} -comment "{desc}"')
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
        self.stream_command(f"set resp [sitr select {module}@{release} {args}]")
        resp = self.stclc_puts_resp()
        if resp:
            LOGGER.error(f"sitr select {resp}")
            return True
        return False

    def stclc_submit_module(
        self, modules: List[str], comment: str, skipcheck: bool = False, email=None
    ) -> bool:
        """submit the specified modules"""

        
        # Content is html <p> snippet so its more customizable
        submit_email_content = dedent(
            """
        <p>New submit to module {mod}.<br/>
        User {user} submitted {mod} new {ver}. <br/>
        Used arguments:.<br/>
        modules={mods}.<br/>
        comment={comment}.<br/>
        skipcheck={skipcheck}.<br/></p>
        """
        )
        # Remove new lines
        submit_email_content.replace("\n", "")


        errors = {}
        vers = {}
        args = f'{"-skipcheck" if skipcheck else ""}'
        for mod in modules:
            resp = self.shell.run_command(
                f'set resp [sitr submit -force -comment "{comment}" {args} {mod}]'
            )

            if resp:
                errors[mod] = resp
                vers[mod] = resp.partition("Tagging:")[-1]

        if errors:
            for mod in errors:
                LOGGER.error(f"submit module {mod} - {errors[mod]}")

            if email is not None:
                for mod in vers:
                    ver = vers[mod].partition(" : Added")[-1].splitlines()[0].strip()
                    content = submit_email_content.format(
                        mod=mod,
                        mods=",".join(modules),
                        user=os.environ.get("USER", "nobody"),
                        ver=ver,
                        comment=comment,
                        skipcheck=skipcheck,
                    )
                    self.email_command_output(email, f"submit {mod}", content)
            return True
        return False

    def stclc_integrate(self, nopop: bool = False, email=None) -> bool:
        """run the sitr integrate command"""
        self.stream_command(
            f'set resp [sitr integrate -noprompt {"-nopop" if nopop else ""}]'
        )
        resp = self.stclc_puts_resp()
        if resp:
            LOGGER.error(f"integrate {resp}")
            if email is not None:
                resp += f"\nUsed arguments:\nnopop={nopop}\n"
                self.email_command_output(email, "integrate", resp)
            return True
        return False

    def stclc_compare(self, args: str = "", args2: str = "") -> None:
        """run the compare command"""
        self.stream_command(f"compare {args} {args2}")

    def email_command_output(self, email: str, command: str, content: str):
        self.send_email(
            subject=f"wtf {command} command",
            sender="wtf script <noreply@qti.qualcomm.com>",
            recipients=[email],
            content=content,
        )

    def stclc_sitr_release(
        self,
        comment: str,
        skip_check: bool = False,
        on_server: bool = False,
        email=None,
    ) -> bool:
        """run the sitr release command"""
        args = f'{"-skipcheck" if skip_check else ""} {"-_fromserver" if on_server else ""}'
        self.stream_command(f'set resp [sitr release -comment "{comment}" {args}]')
        resp = self.stclc_puts_resp()
        if resp:
            LOGGER.error(f"release {resp}")
            if email is not None:
                resp += f"\nUsed arguments:\ncomment={comment}\nskip_check={skip_check}\non_server={on_server}\n"
                self.email_command_output(email, "release", resp)
            return True
        return False

    def stclc_get_branch(self) -> str:
        """Returns the branch we're on, based on SYNC_DEVAREA_TOP"""
        resp = self.shell.run_command("url tags -btags $env(SYNC_DEVAREA_TOP)")
        branch = resp.strip().splitlines()[0].strip()
        return branch

    def stclc_get_url_root(self, module: str = "") -> str:
        """Returns the vault of the top module, based on SYNC_DEVAREA_TOP"""
        if not module:
            module = "$env(SYNC_DEVAREA_TOP)"
        return self.shell.run_command(f"url vault {module}")

    def stclc_create_branch(self, url: str, version: str, comment: str, email=None,) -> bool:
        self.stream_command(
            f'set resp [sitr mkbranch -comment "{comment}" {version} {url}]'
        )
        resp = self.stclc_puts_resp()
        
        if email is not None:
            prj, pr = url.split("%")
            user = getpass.getuser()    
            resp += f"New Branch Requested by user {user} for {prj}_{version} \n Used arguments:\ncomment={comment}\nversion={version}\nurl={prj}\n"
            self.email_command_output(email, "mkbranch", resp)
        return True
        if resp:
            LOGGER.error(f"create branch {resp}")
        return False

    def stclc_puts_resp(self) -> str:
        """check the resp variable for the output from the prev command"""
        return self.shell.run_command(
            f'if [info exists resp] {{ puts $resp }} else {{ puts "ERROR" }}',
            self.test_mode,
        )
    def stream_command(self, cmd: str) -> None:
        """stream the specified command"""
        for resp in self.shell.stream_command(cmd, self.test_mode):
            print(f"{resp}", end="")

    ###############################################
    # Methods that do not interact with stclc
    ###############################################
    # Methods to setup the SITaR environment
    def setup_sitr_env(
        self,
        chip_name: str,
        chip_version: str,
        base_path: "Path",
        role: str = "Design",
        config_name=None,
    ) -> None:
        """setup the env hash for the env variables for SITaR"""
        (project_name, container_name) = get_sitr_proj_info(chip_name, chip_version)
        print(f"project name = {project_name}, container = {container_name}")
        (development_dir, development_name) = get_sitr_dev_info(base_path, project_name)
        print(f"development dir = {development_dir}, name = {development_name}")
        config_root = get_sitr_config_root(development_dir, config_name)
        self.env = {
            "SYNC_PROJECT_CFGDIR": config_root / "Setting",
            "SYNC_PROJECT_CFGDIR_ROOT": config_root,
            "SYNC_DEVELOPMENT_DIR": development_dir,
            "SYNC_DEVAREA_TOP": container_name,
            "SYNC_DEV_ASSIGNMENT": role,
        }

    def force_integrate_mode(self) -> None:
        """set the environment variable to run in Interator mode"""
        self.shell.env["SYNC_DEV_ASSIGNMENT"] = "Integrate"

    def force_version(self, version: str) -> None:
        """set the baseline version of the workspace"""
        self.stclc_set_sitr_alias(version)

    def get_sitr_project_dir(self, sitr_env: Dict) -> "Path":
        """Get the root SITaR project directory"""
        project_dir = self.env["SYNC_DEVELOPMENT_DIR"] / "work"
        return project_dir

    def set_sitr_work_dir(self, work_dir: "Path") -> None:
        """Set the working directory for SITaR"""
        self.env["SYNC_DEVAREA_DIR"] = work_dir

    def get_hrefs(self, url: str) -> List[Dict]:
        """return a list of the different hrefs, each item is a dict with attributes"""
        return parse_kv_response(self.stclc_get_hrefs(url))

    # def show_hrefs(self, url: str, submodule="") -> None:
    #    """Show the hrefs for the specified URL"""
    #    print(f"Showing hrefs for {url}")
    #    hrefs = self.get_hrefs(url)
    #    if not hrefs:
    #        print(f"No hrefs found in {url}")
    #        return []
    #    return self.display_hrefs(url, hrefs, submodule)
    def display_hrefs(self, hrefs: List[Dict]) -> None:
        """Display the hrefs for the specified URL"""
        headers = ["module", "source_url", "url", "selector", "relpath"]
        table = {}
        for header in headers:
            table[header] = [href[header] for href in hrefs if "module" in href]

        print(tabulate.tabulate(table, headers="keys", tablefmt="pretty"))
        print()
        # if table['module']:
        #    #print(f"Displaying Hrefs for {name}")
        #    print(tabulate.tabulate(table, headers="keys", tablefmt="pretty"))
        #    print()
        #    #for href in hrefs:
        #    #    if 'hrefs' in href:
        #    #        if submodule and href['name'] != submodule:
        #    #            continue
        #    #        self.display_hrefs(href['name'], href['hrefs'], submodule)

    def format_hrefs(self, mod: str, submod: str, hrefs: List[Dict]) -> List[Dict]:
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

    def show_module_hrefs(
        self, modules: List[str], submodule: str, fname: str = ""
    ) -> None:
        """show the hrefs of the modules, or use the top module if not specified"""
        if not modules:
            modules = [os.environ["SYNC_DEVAREA_TOP"]]

        rows = []
        for mod in modules:
            rows += self.format_hrefs(mod, submodule, self.get_hrefs(mod))

        if fname:
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
                return 1

        else:
            self.display_hrefs(rows)

    def update_hrefs(self, submodule: str, fname: str) -> int:
        """show the hrefs of the modules, or use the top module if not specified"""
        path = Path(fname)
        if path.suffix == ".csv":
            df = pd.read_csv(fname)
        elif path.suffix == ".xls" or path.suffix == ".xlsx":
            # TODO - specify a tab?
            df = pd.read_excel(fname)
        else:
            LOGGER.error(f"Unsupported file type ({fname})")
            return 1

        for container in df["submodule"].unique():
            if submodule and container != submodule:
                continue
            print(f"Checking the Hrefs for {container}")
            container_hrefs = self.get_hrefs(container)
            updates = []
            for index, href in df[df["submodule"] == container].iterrows():
                if self.add_href(
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
            if prompt_to_continue("Update Hrefs"):
                for href in updates:
                    self.add_href(
                        container,
                        container_hrefs,
                        href["url"],
                        href["relpath"],
                        href["selector"],
                    )
                if prompt_to_continue("Populate Updates"):
                    self.stclc_populate(container, force=True)

    def add_href(
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

    # Method calls for the SITaR commands
    def pop_sitr_modules(self, force: bool = False, modules: List[str] = ()) -> None:
        """populate the list of SITaR modules"""
        status = False
        if modules:
            mod_list = " ".join(modules)
            LOGGER.info(f"Populating {mod_list}")
            status = self.stclc_populate(mod_list, force=force)
        return status

    def populate_tag(
        self, sitr_mods: List[Dict], modules: List[str], tag: str, force: bool = False
    ) -> bool:
        """populate the specified tag in all modules in update mode"""
        errors = []
        for mod in modules:
            path = sitr_mods[mod]["relpath"]
            args = f"-version {tag} -dir {path}"
            if self.stclc_populate(force=force, args=args):
                errors.append(mod)
        if errors:
            LOGGER.warn(
                f"Errors encountered when populating {' '.join(errors)} with the tag {tag}"
            )
            return True
        return False

    def populate_configs(
        self, sitr_mods: List[Dict], config_list: List[str], force: bool = False
    ) -> bool:
        """populate a specified list of module configs if modules are not in update mode"""
        errors = []
        for mod in sitr_mods:
            if sitr_mods[mod]["status"] == "Update":
                continue
            if not mod in config_list:
                continue
            if self.stclc_update_module(mod, config_list[mod]["tagName"]):
                errors.append(mod)
        if errors:
            LOGGER.warn(f"Errors encountered when updating {' '.join(errors)}")
            return True
        return False

    def flat_release_submit(
        self, sitr_mods: List[Dict], tag: str, comment: str, email=None
    ) -> Dict:
        """do the snapshot submits for the flat release and return a list of modules to integrate"""
        modules_to_submit = []
        mod_list = {}
        snap_tag = self.get_snapshot_tagname(tag)
        for mod in sitr_mods:
            if sitr_mods[mod]["status"] == "Update":
                modules_to_submit.append(mod)
                # TODO - what if _v1.2 was used?
                mod_list[mod] = {"module": mod, "tagName": f"{snap_tag}_v1.1"}
            else:
                selector = sitr_mods[mod]["selector"]
                mod_list[mod] = {"module": mod, "tagName": selector}
        if self.check_for_submit_errors(modules_to_submit):
            # TODO - raise exception?
            return {}
        if self.snapshot_submit_module(
            sitr_mods, modules_to_submit, tag, comment, email=email
        ):
            return {}
        return mod_list

    def get_root_url(self, module: str = "", branch: str = "", version: str = "") -> str:
        """Create a branch of the specified module (will be top if not specified)"""
        root = self.stclc_get_url_root(module)
        if branch:
            return f"{root}@{branch}:{version}"
        elif version:
            return f"{root}\;{version}"
        else:
            return root

    def create_branch(self, version: str, module_tag: str, comment: str, email=None,) -> bool:
        """Create a branch of the current top module"""
        url = self.get_root_url(branch=version)
        if self.stclc_mod_exists(url):
            LOGGER.warn(f"The DSync module ({url}) already esists")
            return False
        if self.stclc_create_branch(
            f'{os.environ["SYNC_DEVAREA_TOP"]}%0', version, comment, email=email,
        ):
            return True
        if not self.stclc_mod_exists(url):
            # TODO - raise exception?
            LOGGER.error(f"could not create the sitr module ({url})")
            return True
        if self.stclc_tag_files(module_tag, url):
            return True
        return False

    def branch_modules(
        self, sitr_mods: List[Dict], mod_list: List[str], version: str, comment: str
    ) -> True:
        """branch all of the modules with the versions specified by mod_list"""
        branches = []
        errors = False
        # TODO - do we need to branch submodules?
        for mod in sitr_mods:
            if mod not in mod_list:
                LOGGER.error(f"The module {mod} is not in the module list")
                errors = True
            branches.append({"module": mod, "version": mod_list[mod]["tagName"]})
        if errors:
            return {}

        mod_list = {}
        for branch in branches:
            url = self.get_root_url(module=branch["module"], version=branch["version"])
            branched_url = self.get_root_url(
                module=branch["module"], version=f"{version}_v1.1"
            )
            if self.stclc_create_branch(url, version, comment):
                errors = True
            if not self.stclc_mod_exists(branched_url):
                LOGGER.error(f"could not create the sitr module ({branched_url})")
            mod_list[branch] = {"module": mod, "tagName": f"{version}_v1.1"}
        if errors:
            return {}
        return mod_list

    def checkin_module(self, modules: List[str], comment: str) -> bool:
        """check in the specified design sync modules"""
        if modules:
            mod_list = " ".join(modules)
            LOGGER.info(f"Populating {mod_list}")
            return self.stclc_check_in(mod_list, comment, rec=True)
        return False

    def get_module_checkouts(self, module: str, filter: str = "") -> List[Dict]:
        """get a list of files that are checked out in the specified module"""
        resp = self.stclc_module_checkouts(module, filter)
        resp = parse_kv_response(resp)
        if resp:
            return get_files(resp[0])
        return []

    def get_module_modified(self, module: str, filter: str = "") -> List[Dict]:
        """get a list of files that are modified in the specified module"""
        resp = self.stclc_module_modified(module, filter)
        resp = parse_kv_response(resp)
        if resp:
            return get_files(resp[0])
        return []

    def get_unmanaged(self, path: str, filter: str = "") -> List[Dict]:
        """get a list of files that are modified in the specified module"""
        resp = self.stclc_unmanaged(path, filter)
        resp = parse_kv_response(resp)
        if resp:
            return get_files(resp[0])
        return []

    def compare(
        self,
        sitr_mods: List[Dict],
        modules: List[str],
        tag: str,
        is_trunk: bool,
        is_baseline: bool,
    ) -> None:
        """Run the compare on the specified modules, vs trunk or tag or baseline"""
        args = "-rec -path"
        select = "selector"
        if tag:
            args += f" -{select} {tag}"
            select = "selector2"
        if is_trunk:
            branch = self.stclc_get_branch()
            if not branch.endswith(":"):
                branch += ":"
            args += f" -{select} {branch}"
            select = "selector2"
        for mod in modules:
            args2 = ""
            if sitr_mods[mod]["status"] != "Update":
                print(f"Skipping {mod} since it is not in update mode")
                continue
            if is_baseline:
                args2 = f'-{select} {sitr_mods[mod]["baseline"]}'
            args2 += f" {mod}"
            print(f"Scanning {mod}")
            self.stclc_compare(args, args2)

    def check_tag(self, sitr_mods: List[Dict], modules: List[str], tag: str) -> None:
        """Check the specified tag and display the versions of the files that were tagged"""
        if not tag:
            tag = self.stclc_get_branch()
            # get branch returns a selector which must end with :
            if not tag.endswith(":"):
                tag += ":"
        for mod in modules:
            if sitr_mods[mod]["status"] != "Update":
                print(f"Skipping {mod} since it is not in update mode")
                continue
            print(f"Scanning {mod}")
            path = sitr_mods[mod]["relpath"]
            resp = self.stclc_module_contents(mod, tag, path)
            parsed = parse_kv_response(
                "\n".join(resp.splitlines()[1:-1])
            )  # skip first/last line
            if not parsed:
                print(f"No matching files for {tag}")
                continue
            files = get_files(parsed)
            headers = ["name", "version"]
            table = {}
            for header in headers:
                table[header] = [file[header] for file in files]
            print(tabulate.tabulate(table, headers="keys", tablefmt="pretty"))

    def show_locks(self, modules: List[str]) -> None:
        """Display the files that are locked in the list of modules"""
        for mod in modules:
            print(f"Scanning {mod}")
            resp = self.stclc_module_locks(mod)
            parsed = parse_kv_response(resp)
            if not parsed or not "contents" in parsed[0]:
                print(f"No checkouts")
                continue
            headers = ["user", "name", "where"]
            table = {}
            for header in headers:
                table[header] = [item[header] for item in parsed[0]["contents"]]
            print(tabulate.tabulate(table, headers="keys", tablefmt="psql"))

    def get_sitr_modules(self) -> Dict:
        """return the SITaR modules and their status"""
        modules = {}
        keys = ["selector", "baseline", "relpath", "status"]
        resp = self.stclc_sitr_status()
        for line in resp.split("\n"):
            if not line.startswith(" "):
                continue
            items = line.split()
            first_item = next(iter(items), "")
            if "%" in first_item:
                modules[first_item[:-2]] = dict(zip(keys, items[1:]))
        return modules

    def vhistory(self, modules: List[str]) -> None:
        """runs vhistory for modules"""
        for mod in modules:
            self.run_output(f"vhistory {mod}")

    def sitr_status(self) -> None:
        """send the sitr status command and stream the output"""
        resp = self.stclc_sitr_status()
        print(f"{resp}")

    def run_output(self, command: str) -> None:
        """runs command, printing output, except last line (prompt)"""
        response = self.shell.run_command(command)
        print("\n".join(response.strip().splitlines()[:-1]))

    def update_module(self, modules: List[str], config: str = "") -> bool:
        """put the modules specified into update mode"""
        if not config:
            # Discover config version from the workspace
            config = self.stclc_get_branch()
            if not config.endswith(":"):
                # Suffix : seems to matter
                config += ":"
        errors = []
        for mod in modules:
            if self.stclc_update_module(mod, config):
                errors.append(mod)
        if errors:
            LOGGER.warn(
                f"Errors encountered when updating {' '.join(errors)} with the config {config}"
            )
            return True
        return False

    def display_mod_files(self, files: List[Dict], version: bool = False) -> None:
        """display the list of modified files in a table"""
        if version:
            headers = ["name", "fetchedstate", "mtime"]
        else:
            headers = ["name", "version", "mtime"]
        table = {}
        for header in headers:
            table[header] = [file[header] for file in files]
        print(tabulate.tabulate(table, headers="keys", tablefmt="grid"))

    def show_checkouts(self, modules: List[str]) -> None:
        """Display a list of the files checked out in the specified modules"""
        for mod in modules:
            print(f"Scanning {mod}")
            files = self.get_module_checkouts(mod)
            if not files:
                print(f"No checkouts")
                continue
            self.display_mod_files(files)

    def overlay_tag(self, sitr_mods: List[Dict], modules: List[str], tag: str) -> None:
        """Display a list of the files checked out in the specified modules"""
        errors = []
        for mod in modules:
            if sitr_mods[mod]["status"] != "Update":
                LOGGER.warn(f"Ignoring the module {mod} since it is not in Update mode")
                continue
            comment = f"Overlaying {tag} on the module {mod}"
            if self.stclc_populate(f"{mod}:0", rec=False):
                errors.append(mod)
                continue
            if self.stclc_check_in(f"{mod}:0", comment=comment, args="-noiflock"):
                errors.append(mod)
        if errors:
            LOGGER.warn(
                f"Errors encountered when overlaying the {' '.join(errors)} modules with the tag {tag}"
            )
            return True
        return False

    def restore_module(self, sitr_mods: List[Dict], modules: List[str]) -> None:
        """put the modules specified back into mcache mode"""
        for mod in modules:
            print(f"Restoring {mod} to version {sitr_mods[mod]['baseline']}")
            self.update_module([mod], sitr_mods[mod]["baseline"])

    def show_unmanaged(self, sitr_mods: List[Dict], modules: List[str]) -> None:
        """check the unmanaged files in the module and display the files"""
        for mod in modules:
            print(f"Scanning {mod}")
            path = sitr_mods[mod]["relpath"]
            files = self.get_unmanaged(path)
            if files:
                LOGGER.warn(f"The module {mod} has the following unmanaged files")
                self.display_mod_files(files)
                continue

    def tag_sch_sym(self, sitr_mods: List[Dict], modules: List[str], tag: str) -> bool:
        """Check to make sure that all sch/sym are checked in, then tag them with the provided tag"""
        args = "-rec -filter +.../schematic.sync.cds,+.../symbol.sync.cds"
        errors = []
        for mod in modules:
            files = self.get_module_checkouts(mod, filter)
            LOGGER.debug(f"results from show checkouts = {files}")
            if files:
                LOGGER.warn(f"The module {mod} has checkouts and cannot be tagged")
                self.display_mod_files(files)
                continue
            files = self.get_module_modified(mod, filter)
            LOGGER.debug(f"results from show modified = {files}")
            if files:
                LOGGER.warn(f"The module {mod} has modified files and cannot be tagged")
                self.display_mod_files(files)
                continue
            path = sitr_mods[mod]["relpath"]
            resp = self.shell.run_command(f"cdws")
            print(f"Tagging {mod} with {tag}")
            if self.stclc_tag_files(tag, path, args=args):
                errors.append(mod)
        if errors:
            LOGGER.warn(
                f"Errors encountered when populating {' '.join(errors)} with the tag {tag}"
            )
            return True
        return False

    def snapshot_add_submodules(
        self, tag: str, mod: str, hrefs: List[Dict], args: str = ""
    ) -> bool:
        """for all of the hrefs, add the snapshot version to the snapshot version of the module"""
        status = False
        for href in hrefs:
            if href["type"] == "Module":
                if self.stclc_tag_files(tag, f"{href['name']}%0", args=args):
                    status = True
                else:
                    self.stclc_add_mod(
                        f"[url vault {mod}]\;{tag}",
                        f"{href['url']}\;{tag}",
                        href["relpath"],
                    )
            elif href["type"] == "Branch":
                url = href["url"]
                if href["selector"]:
                    url += f"@{href['selector']}"
                self.stclc_add_mod(f"[url vault {mod}]\;{tag}", url, href["relpath"])
            else:
                LOGGER.error(
                    f"Unknown href type for {mod}->{href['url']} ({href['type']})"
                )
                status = True
        return status

    def get_snapshot_tagname(self, tag: str) -> str:
        # Check what branch we're on
        branch = self.stclc_get_branch()
        # On trunk, add REL_ prefix to the tag, otherwise add
        # uppercased branch + "_" as prefix to the tag.
        snap_tag = (
            f"REL_{tag}" if "trunk" in branch.lower() else f"{branch.upper()}_{tag}"
        )
        return snap_tag

    def check_for_submit_errors(self, modules: List[str]) -> bool:
        """check modules for erros that would prevent the submit"""
        errors = set()
        for mod in modules:
            files = self.get_module_checkouts(mod)
            LOGGER.debug(f"results from show checkouts = {files}")
            if files:
                LOGGER.warn(f"The module {mod} has checkouts and cannot be submitted")
                self.display_mod_files(files)
                errors.add(mod)
                continue
            files = self.get_module_modified(mod)
            LOGGER.debug(f"results from show modified = {files}")
            if files:
                LOGGER.warn(
                    f"The module {mod} has modified files and cannot be submitted"
                )
                self.display_mod_files(files)
                errors.add(mod)
        if errors:
            LOGGER.warn(
                f"Errors encountered when submitting the {' '.join(errors)} modules"
            )
            return True
        return False

    def snapshot_submit_module(
        self,
        sitr_mods: List[Dict],
        modules: List[str],
        tag: str,
        comment: str,
        email=None,
    ) -> bool:
        """perform the snapshot submit on the specified modules with the specified tag"""
        snap_tag_base = self.get_snapshot_tagname(tag)
        errors = set()
        for mod in modules:
            print(f"Performing the snapshot submit on {mod} with {snap_tag_base}")
            # TODO - need to check if this tag exists, then the tag should be _v1.2
            snap_tag = snap_tag_base + "_v1.1"
            LOGGER.debug(f"Using snapshot tag {snap_tag} for module {mod}")
            path = sitr_mods[mod]["relpath"]
            selector = sitr_mods[mod]["selector"]
            args = "-rec -immutable -comment {comment}"
            hrefs = self.get_hrefs(mod)
            if hrefs:
                args += f" -filter {','.join([x['relpath'] for x in hrefs])}"
            if self.stclc_tag_files(snap_tag, path, args=args):
                # TODO - raise exception?
                errors.add(mod)
            elif self.snapshot_add_submodules(snap_tag, mod, hrefs, args="-immutable"):
                # TODO - raise exception?
                errors.add(mod)

        if email is not None:
            resp = f"\nUsed arguments:\nmodules={','.join(modules)}\ntag={tag}\ncomment={comment}\n"
            self.email_command_output(email, "snapshot submit", resp)

        if errors:
            LOGGER.warn(
                f"Errors encountered when submitting the {' '.join(errors)} modules"
            )
            return True
        return False

    def make_module_readme(self, path: Path, comment: str) -> Path:
        """make a readme file for the module"""
        readme = path / "README.txt"
        if readme.exists():
            return readme
        readme.write_text(comment)
        return readme

    def make_tapeout_ws(self, sitr_mods: List[Dict], tag: str) -> bool:
        """tag the files and modules with the tapeout tag to create the tapeout ws"""
        for mod in sitr_mods:
            if sitr_mods[mod]["status"] != "Update":
                LOGGER.warn(f"The {mod} module is not in Update mode")
                continue
            relpath = sitr_mods[mod]["relpath"]
            path = Path(os.environ["DSGN_PROJ"]) / relpath
            readme = self.make_module_readme(path, f"SITaR module for {mod}")
            if readme.exists():
                file_status = self.stclc_get_file_status(str(readme))
                if file_status["props"]["version"] == "Unmanaged":
                    if self.stclc_check_in(str(readme), "Initial version"):
                        readme = ""
            else:
                readme = ""
            if mod == "CONFIG":
                self.stclc_tag_files(tag, path, args="-rec -modified")
            if readme:
                self.stclc_tag_files(tag, str(readme), "-modified")
            cds_lib = Path(path) / "design_libs/cds.lib.design_lib"
            if cds_lib.exists():
                self.stclc_tag_files(tag, str(cds_lib), "-modified")
            cds_lib = Path(path) / "sim_libs/cds.lib.sim_libs"
            if cds_lib.exists():
                self.stclc_tag_files(tag, str(cds_lib), "-modified")
            hrefs = self.get_hrefs(mod)
            self.snapshot_add_submodules(tag, mod, hrefs)

    def get_ws_devname(self) -> str:
        config = self.stclc_get_branch()
        if config == "Trunk":
            config = "v100"
        return f'{os.environ["SYNC_DEVAREA_TOP"]}_{config}'.lower()

    def get_tapeout_tag(self) -> str:
        return f"tapeout_{self.get_ws_devname()}".lower()

    def setup_tapeout_ws(self, sitr_mods: List[Dict], tag: str) -> bool:
        """put all of the modules into update mode with the tapeout selector"""
        errors = []
        for mod in sitr_mods:
            if sitr_mods[mod]["status"] != "Update":
                LOGGER.warn(f"The {mod} module is not in Update mode")
            elif sitr_mods[mod]["selector"] != tag:
                LOGGER.warn(
                    f'The {mod} module selector is set to {sitr_mods[mod]["selector"]}'
                )
            else:
                continue
            # FIXME: BROKEN - no `root` below
            if self.update_module([mod], root.stem):
                errors.append(mod)
        if errors:
            LOGGER.warn(
                f"Errors encountered when updating the {' '.join(errors)} modules"
            )
            return True
        return False

    def setup_shared_ws(self, sitr_mods: List[Dict]) -> bool:
        """put all of the modules into update mode"""
        # Discover config version from the workspace
        config = self.stclc_get_branch()
        if not config.endswith(":"):
            # Suffix : seems to matter
            config += ":"
        errors = []
        for mod in sitr_mods:
            if sitr_mods[mod]["status"] != "Update":
                LOGGER.warn(f"The {mod} module is not in Update mode")

            # FIXME: BROKEN: no `tag` below!
            elif sitr_mods[mod]["selector"] != tag:
                LOGGER.warn(
                    f'The {mod} module selector is set to {sitr_mods[mod]["selector"]}'
                )
            else:
                continue
            if self.update_module([mod]):
                errors.append(mod)
        if errors:
            LOGGER.warn(
                f"Errors encountered when updating the {' '.join(errors)} modules"
            )
            return True
        return False

    def submit(
        self,
        populate: bool,
        tag: str,
        sitr_modules: List[str],
        modules: List[str],
        comment: str,
        email=None,
    ) -> bool:
        """Runs a normal submit or a snapshot submit, depending on args"""
        skipcheck = False
        if tag and populate:
            LOGGER.error("Cannot use -n TAG with --pop!")
            return True
        if self.check_for_submit_errors(modules):
            # TODO - raise exception?
            return True
        if populate:
            # First populate, then normal submit
            # TODO - add in the skip check
            self.pop_sitr_modules(modules=modules)
            # TODO - do this all of the time?
            self.checkin_module(modules, comment)
            skipcheck = True
        elif tag:
            # Run snapshot submit only
            return self.snapshot_submit_module(sitr_modules, modules, tag, comment)
        return self.stclc_submit_module(modules, comment, skipcheck, email=email)

    def update_module_snapshot(
        self, sitr_mods: List[Dict], modules: List[str], force: bool = False
    ) -> None:
        """update the specified modules and populate the baseline tag"""
        status = False
        for mod in modules:
            if sitr_mods[mod]["status"] != "Update":
                self.update_module([mod])
            tag = sitr_mods[mod]["baseline"]
            status += self.populate_tag(sitr_mods, [mod], tag, force)
        return status

    def get_sitr_update_list(self, modules: List[str] = ()) -> List[str]:
        """get a list of submits that are ready to integrate"""
        if not modules:
            modules = [""]
        resp_list = []
        for mod in modules:
            print(f"Scanning {mod}")
            resp = self.stclc_sitr_lookup(mod)
            resp_list.append(resp)
        return self.process_sitr_update_list(resp_list)

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

    def display_mod_list(self, mod_list: List[Dict]) -> None:
        """Display the detected module updates"""
        # TODO - include date
        # datetime.datetime.fromtimestamp(table['date']).strftime('%m-%d-%Y %H:%M:%S')
        headers = ["module", "tagName", "author", "comment"]
        table = {}
        for header in headers:
            table[header] = [mod_list[mod][header] for mod in mod_list]
        table["date"] = [
            datetime.datetime.fromtimestamp(int(mod_list[mod]["date"])).strftime(
                "%m-%d-%Y %H:%M:%S"
            )
            for mod in mod_list
        ]
        print(tabulate.tabulate(table, headers="keys", tablefmt="pretty"))

    def sitr_integrate(
        self, mod_list: List[Dict] = None, nopop: bool = False, email=None
    ) -> bool:
        """run the SITaR integrate"""
        errors = []
        if mod_list:
            # Check what branch we're on
            branch = self.stclc_get_branch()
            # Only allow tags with certain prefixes, based on the branch
            # TODO - this filter needs to be in lookup not integrate
            is_trunk = "trunk" in branch.lower()
            allowed_prefixes = ["REL_", "v1."] if is_trunk else [branch]
            for module, mod in mod_list.items():
                module_name = mod["module"]
                module_tag = mod["tagName"]
                if not any(module_tag.startswith(p) for p in allowed_prefixes):
                    LOGGER.warning(
                        f"Ignoring not allowed tag {module_tag} for module {module_name} on selector {branch}"
                    )
                    # TODO - raise exception?
                    continue
                # TODO - are errors detected?
                print(f"Integrating mod {module_name} with tag {module_tag}")
                if self.stclc_add_sitr_mod(module_name, module_tag):
                    # TODO - raise exception?
                    errors.append(module_name)
        if errors:
            # TODO - raise exception?
            LOGGER.warn(
                f"Errors encountered when submitting the {' '.join(errors)} modules"
            )
            return True
        return self.stclc_integrate(nopop, email=email)

    def sitr_release(
        self,
        comment: str,
        skip_check: bool = False,
        on_server: bool = False,
        email=None,
    ) -> bool:
        """perform the sitr release"""
        return self.stclc_sitr_release(
            comment, skip_check=skip_check, on_server=on_server, email=email
        )

    def get_module_info(self, module: str = "") -> Dict:
        if not module:
            module = "$env(SYNC_DEVAREA_TOP)"
        resp = self.stclc_module_info(module)
        resp = parse_kv_response(resp)
        return resp["actual"]

    def showstatus(self, modules) -> int:
        """Runs showstatus command for each module (or top module if none given)"""
        table = defaultdict(list)
        if not modules:
            modules = ["$env(SYNC_DEVAREA_TOP)"]
        report = []
        for mod in modules:
            resp = self.stclc_module_status(mod)
            report.extend(
                list(filter(None, map(str.strip, resp.splitlines())))[:-1]
            )  # skip prompt
        last_mod = ""
        errors = []
        for line in report:
            if "%0" not in line:
                # Report errors at the end
                errors += [line]
                continue
            mod, _, msg = line.partition(": ")
            if mod != last_mod and last_mod != "":
                # Add separators between modules
                table["module"] += ["-" * 20]
                table["status"] += ["-" * 40]

            table["module"] += [
                mod if mod != last_mod else ""
            ]  # don't repeat module on each line
            table["status"] += [msg.strip()]
            last_mod = mod

        print(tabulate.tabulate(table, headers="keys", tablefmt="pretty"))
        if errors:
            errors = "\n".join(errors)
            print(f"\nERRORS:\n\n{errors}\n")

        return 0

    def parse_project_xml(
        self, fname: Path, section="wtf", key="email_notify"
    ) -> str:
        """
        Parses given project.xml file and extracts the value of `key` attribute from
        top-level element `section` -> `<values>`.
        """
        if not fname.exists():
            LOGGER.error("%s NOT found", str(fname))
            return ""

        et = ET()
        doc = et.parse(str(fname))

        try:
            section = doc.find(section)
            values = section.find("values")
            anon = values.find("anon")
            value = anon.attrib[key]
            return value
        except Exception as err:
            LOGGER.exception("Cannot parse %s: %s", str(fname), str(err))
            return ""

    def send_email(
        self,
        subject: str,
        sender: str,
        recipients: List[str],
        content: str,
        smtp_host: str = "localhost",
    ) -> int:
        """
        Sends an email with `subject`, from `sender` to `recipients` with the given
        `content` body using Email.html template.
        """
     
        # Load Email.html template
        
        import jinja2
        
        File_path =  str(Path(os.environ["RFA_MODELERS_DIR"])/"dm")
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(searchpath = "/prj/analog/blaster_eval/sandiego/chips/reference/reference_v100/work/mgajjar/REFERENCE/verif_modules/rfa_modelers/python3/dm/"))
        #env = jinja2.Environment(loader=jinja2.FileSystemLoader(searchpath = File_path))
        Email_file = "Email.html"
        mail_template = env.get_template(Email_file)

        # Place contents in content template placeholder
        html_body = mail_template.render(content=content)

        msg = MIMEMultipart("alternative")

        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(html_body, "html"))
        s = smtplib.SMTP(smtp_host)
        s.send_message(msg)
        s.quit()
        #try:
        #    with smtplib.SMTP(smtp_host) as server:
        #        server.starttls()
        #        server.send_message(msg)
        #except Exception:
        #   LOGGER.exception("Could not send Email.")
        #   return 1

        return 0


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
    path_of_script = Path(__file__).absolute().parent
    sys.path.append(str(path_of_script))
    from spreadsheet import Spreadsheet_xls

    ss = Spreadsheet_xls()
    if args.xls:
        ss.open_ss(args.xls)
        ss.set_active_sheet_no(0)
        ss.set_header_key("CORE NAME")
    if args.test:
        import doctest

        doctest.testmod()
    if args.directory:
        start_dir = args.directory
    else:
        start_dir = Path.cwd()
    print(f"start dir = {start_dir}")
    dm = Dsync(cwd=start_dir, test_mode=args.test)
    root_dir = get_sitr_root_dir(start_dir)
    shrc_project = root_dir / ".shrc.project"
    if shrc_project.exists():
        print(f"setting source file to be {shrc_project}")
        dm.set_shrc_project(shrc_project)
    dm_shell = Process.Process()
    dm.configure_shell(dm_shell)
    with dm_shell.run_shell():
        print("Waiting for DM shell")
        if not dm_shell.wait_for_shell():
            print("Timeout waiting for DM shell")
        container = dm.stclc_current_module()
        print(f"Found the container {container}")
        if args.xls:
            for href in ss.rows_after_header():
                relpath = href["CORE NAME"]
                url = href["DESIGNSYNC INFORMATION"]
                if url:
                    # TODO - this needs to be updated
                    dm.add_href(container, url, relpath, test_flag=True)
            if Dsync.prompt_to_continue():
                for href in ss.rows_after_header():
                    relpath = href["CORE NAME"]
                    url = href["DESIGNSYNC INFORMATION"]
                    if url:
                        # TODO - this needs to be updated
                        dm.add_href(container, url, relpath, test_flag=True)
        if args.interactive:
            import IPython  # type: ignore

            IPython.embed()  # jump to ipython shell


if __name__ == "__main__":
    main()

