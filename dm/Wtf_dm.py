#! /pkg/qct/software/python/3.6.0/bin/python
"""
Supports running SITaR commands via a DM shell.
"""
import argparse
import getpass
import os
import re
import tempfile
from pathlib import Path
from typing import List


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


class Wtf_dm(dm.Sitar_dm):
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
    def __init__(self, **kwargs) -> None:
        """Constructor for the Sitar class"""
        super().__init__(**kwargs)
        self.sitr_mods = []
        self.modules = []
        self.mod_list = []
        self.module_given = False
        self.dev_dir = None
        self.version = None

    @property
    def email(self):
        email = dm.get_email(Path(os.environ["QC_CONFIG_DIR"]), user=getpass.getuser())
        return email

    def wtf_get_sitr_modules(self, given_mods: List, only_update: bool = False):
        """
        Returns all and the effective modules that are available (or explicitly
        given) depending on the command.
        """
        self.module_given = bool(given_mods)
        self.sitr_mods = self.get_sitr_modules()
        if not given_mods:
            given_mods = list(self.sitr_mods.keys())
        self.modules = []
        for mod in given_mods:
            if mod not in self.sitr_mods:
                LOGGER.warn(f"The module {mod} does not exist in this workspace")
                continue
            if "status" not in self.sitr_mods[mod]:
                continue
            LOGGER.debug(
                f"mod = {mod}, "
                f"path = {self.sitr_mods[mod]['relpath']}, "
                f"status = {self.sitr_mods[mod]['status']}"
            )
            if only_update:
                if self.sitr_mods[mod]["status"] != "Update mode":
                    LOGGER.warn(f"The module {mod} is not in update mode")
                    continue
            self.modules.append(mod)
        if not self.modules:
            self.modules = self.sitr_mods

    def populate(self, force: bool = False) -> int:
        """Populate a SITaR workspace"""
        if self.workspace_type == "Tapeout":
            self.setup_tapeout_ws(self.sitr_mods, self.tapeout_tag)
            self.dssc_pop_modules(self.sitr_mods)
        else:
            if self.workspace_type == "Shared":
                self.setup_shared_ws(self.sitr_mods)
            self.stclc_populate_workspace(force)
        return 0

    def pop_modules(self, force: bool = False) -> int:
        """Populate all modules in update mode in the SITaR workspace"""
        self.dssc_pop_modules(self.modules, force)
        return 0

    def populate_tag(self, tag: str, force: bool = False) -> int:
        """Populate a tag in a SITaR workspace when modules are in update mode"""
        self.sitr_populate_tag(self.sitr_mods, self.modules, tag, force)
        return 0

    def pop_latest(self, tag: str = "", force: bool = False) -> int:
        """Populate a SITaR workspace for the flat release flow"""
        if self.workspace_type == "Tapeout":
            # TODO - need to get the tapeout tag
            self.setup_tapeout_ws(self.sitr_mods, tapeout_tag, force)
            self.dssc_pop_modules(self.sitr_mods)
        elif self.workspace_type == "Shared":
            self.setup_shared_ws(self.sitr_mods)
            self.stclc_populate_workspace(force)
        else:
            self.stclc_populate_workspace(force)
            if tag:
                self.sitr_populate_tag(self.sitr_mods, self.modules, tag)
            mcache_list = [
                mod
                for mod in self.sitr_mods
                if self.sitr_mods[mod]["status"] != "Update mode"
            ]
            self.mod_list = self.get_sitr_update_list(mcache_list)
            self.sitr_populate_configs(self.sitr_mods, self.mod_list)
            # TODO - run voos
            # TODO - send email
        return 0

    def status(self) -> int:
        """Perform a SITaR status"""
        self.sitr_status()
        return 0

    def update(self, config: str = "", delta: bool = False) -> int:
        """Set module(s) (or all modules) in update mode"""
        # TODO - do we need the force switch? Or no overwrite?
        if delta:
            self.update_module_snapshot(self.sitr_mods, self.modules)
        else:
            self.update_module(self.modules, config)
        return 0

    def restore(self) -> int:
        """Restore the specified module to the latest baseline"""
        self.restore_module(self.sitr_mods, self.modules)

        return 0

    def show_checkouts(self) -> int:
        """Scan for checkouts in the module"""
        self.dssc_show_checkouts(self.modules)
        return 0

    def show_locks(self) -> int:
        """Show the files locked in the module module"""
        self.dssc_show_locks(self.modules)
        return 0

    def show_unmanaged(self) -> int:
        """Show unmanaged files in the specified modules"""
        self.sitr_show_unmanaged(self.sitr_mods, self.modules)
        return 0

    def showstatus(self) -> int:
        """Runs showstatus command for the modules"""
        # When no explicit modules are given, pass none.
        modules = self.modules if self.module_given else []
        self.sitr_showstatus(modules)
        return 0

    def showhrefs(self, submod: str = "", fname: str = "") -> int:
        """Show the Hrefs for the specified modules"""
        href_args = (self.modules if self.module_given else [], submod)
        self.dssc_show_module_hrefs(*href_args, fname)
        return 0

    def updatehrefs(self, submod: str = "", fname: str = "") -> int:
        """Update Hrefs from a XLS file, optionally filtering by submodule"""
        self.dssc_update_hrefs(submod, fname)
        return 0

    def check_tag(self, tag: str) -> int:
        """Checks for the TAG for files in MODULE"""
        return self.sitr_check_tag(self.sitr_mods, self.modules, tag)

    def compare(
        self, tag: str = "", trunk: bool = False, baseline: bool = False
    ) -> int:
        """Run a compare on the specified MODULES vs Trunk/Version/Tag"""
        return self.sitr_compare(self.sitr_mods, self.modules, tag, trunk, baseline)

    def vhistory(self) -> int:
        """This command will display the version history for the module"""
        self.dssc_vhistory(self.modules)
        return 0

    def overlay_tag(self, tag: str) -> int:
        """Overlay the specified tag in the specified modules and check-in"""
        self.sitr_overlay_tag(self.sitr_mods, self.modules, tag)
        return 0

    def setup_ws(self) -> int:
        """Setup a workspace after it has been created"""
        if self.workspace_type == "Tapeout":
            # TODO - need to setup the tapeout ttag
            self.setup_tapeout_ws(self.sitr_mods, self.tapeout_tag)
        elif self.workspace_type == "Shared":
            self.setup_shared_ws(self.sitr_mods)
        else:
            self.stclc_populate_workspace()
        # TODO - send email
        return 0

    def submit(
        self, tag: str = "", pop: bool = False, comment: str = "", noemail: bool = False
    ) -> int:
        """Perform a SITaR submit / snapshot submit"""
        email = None
        if not noemail:
            email = self.email

        return self.sitr_submit(
            pop, tag, self.sitr_mods, self.modules, comment, email=email
        )

    def mk_tapeout_ws(self, tag: str = "") -> int:
        """Make the tapeout workspace for the project"""
        if not tag:
            tag = self.get_tapeout_tag()
        else:
            tag = tag.lower()
        if not tag.startswith("tapeout"):
            LOGGER.error("The tag must start with tapeout.")
            return 1
        self.ws_name = tag
        self.dev_name = self.get_ws_devname()
        self.make_tapeout_ws(self.sitr_mods, tag)
        return 0

    def request_branch(self, version: str, comment: str, email=None) -> int:
        """Request a branch for the current project"""
        sitr_alias = f"baseline_{version}"
        # TODO - check for errors
        self.create_branch(version, sitr_alias, comment, email=email)

    # TODO - move this to sitar.py
    def get_development_dir(self, version: str) -> Path:
        # TODO - need to mock this out
        base_path = Path(os.environ["SYNC_DEVELOPMENT_DIR"]).parent
        chip_name = os.environ["SYNC_DEVAREA_TOP"]
        # TODO - call the methods from sitar
        # (project_name, container_name) = Dsync.get_sitr_proj_info(chip_name, version)
        project_name = chip_name + "_" + version
        container_name = chip_name.upper()
        # (development_dir, development_name) = Dsync.get_sitr_dev_info(base_path, project_name)
        development_dir = base_path / project_name.lower()
        development_name = project_name.upper()
        return development_dir

    # TODO - need a switch to use the existing modules populated in the WS
    def mk_branch(
        self, version: str, comment: str, tag: str = "", tapeout: str = ""
    ) -> int:
        """Make a branch in the current workspace where the tapeout tag is populated"""
        if tapeout:
            tapeout = tapeout.lower()
        else:
            tapeout = self.get_tapeout_tag()
        if not tapeout.startswith("tapeout"):
            LOGGER.error("The tapeout tag must start with tapeout.")
            return 1
        tag = tag if tag else f"branch_{self.get_ws_devname()}_to_{version}".lower()

        development_dir = self.get_development_dir(version)
        if not development_dir.is_dir():
            LOGGER.error(
                f"The development for the branch {version} has not been setup. Cannot find {development_dir}."
            )
            return 5

        url = self.dssc_get_root_url(branch=version)
        if not self.stclc_mod_exists(url):
            LOGGER.error(f"The top level url ({url}) does not exist.")
            return 2
        if self.workspace_type == "Tapeout":
            LOGGER.error("Cannot make a branch in a Tapeout workspace.")
            return 3
        # TODO - should this be pop_modules?
        self.stclc_populate_workspace()
        self.sitr_populate_tag(self.sitr_mods, self.sitr_mods, tapeout)
        # TODO - add a cmd line argument to skip the checks for branching
        self.mod_list = self.flat_release_submit(self.sitr_mods, tag, comment)
        self.dev_dir = development_dir
        if not self.mod_list:
            return 4
        return 0

    def mk_branch_int(self, version: str, comment) -> int:
        branch = self.stclc_get_branch()
        mod_list = self.branch_modules(self.sitr_mods, self.mod_list, version, comment)
        if mod_list:
            self.sitr_integrate(mod_list, nopop=True)
            self.sitr_release(comment, skip_check=True, on_server=True)
        return 0

    def mk_release(self, tag: str, comment: str, noemail: bool = False) -> int:
        """Make a SITaR select/integrate/release based on the current workspace"""
        email = None
        if not noemail:
            email = self.email

        self.mod_list = self.flat_release_submit(
            self.sitr_mods, tag, comment, email=email
        )
        if not self.mod_list:
            return 1
        # TODO - do we need to store this?
        self.version = tag
        return 0

    def mk_release_int(self, comment: str) -> int:
        self.sitr_integrate(self.mod_list, nopop=True)
        self.sitr_release(comment, skip_check=True, on_server=True)
        return 0

    def lookup(self, fname: str = "") -> int:
        """Generate a report of submits that are ready to integrate"""
        # TODO - add in support for the all switch
        mod_list = self.get_sitr_update_list(self.modules)
        if not mod_list:
            LOGGER.info("No new submits to integrate")
        elif fname:
            self.io.write_mod_versions(mod_list, fname)
        else:
            self.io.display_mod_list(mod_list)
        return 0

    def integrate(self, fname: str = "") -> int:
        """Run integrate command (must be run as Integrator)"""
        if fname:
            mod_list = self.io.read_mod_versions(fname)
        else:
            mod_list = self.get_sitr_update_list(self.modules)
        if not mod_list:
            LOGGER.warn("Nothing to integrate")
        else:
            self.io.display_mod_list(mod_list)
            if self.io.prompt_to_continue():
                self.sitr_integrate(mod_list)
        return 0

    def int_release(self, comment: str, fname: str = "", noemail: bool = False) -> int:
        """Perform a SITaR integrate and release (must be run as Integrator)"""
        if fname:
            mod_list = read_mod_versions(fname)
        else:
            mod_list = self.get_sitr_update_list(self.modules)
        if not mod_list:
            LOGGER.warn("Nothing to integrate")
        else:
            self.io.display_mod_list(mod_list)
            if self.io.prompt_to_continue():
                self.sitr_integrate(mod_list)
        email = None
        if not noemail:
            email = self.email

        return self.sitr_release(comment, email=email)

    def release(self, comment: str, noemail: bool = False) -> int:
        """Perform a SITaR release only (must be run as Integrator)"""
        email = None
        if not noemail:
            email = self.email

        return self.sitr_release(comment, email=email)

    def diag_basic_checks(self) -> bool:
        """Perform some basic diag checks and return True for a bad error"""
        if not self.sitr_mods:
            LOGGER.error("No SITaR modules found.")
            return True
        root_dir = self.stclc_get_url_root_dir(self)
        # TODO - why does this not work?
        #if root_dir != os.environ['SYNC_DEVAREA_DIR']:
        #    LOGGER.error(f"Invalid url root {root_dir}, should be {os.environ['SYNC_DEVAREA_DIR']}.")
        #    #return True
        return False

    def diag_module_checks(self, interactive: bool = True) -> bool:
        """scan through all dsync modules and return True for a bad error"""
        mod_list = []
        mods = self.dssc_get_all_modules()
        for mod in mods:
            if not mod['modinstname'].endswith('%0'):
                LOGGER.error(f"Bad module instance name {mod['modinstname']}.")
                if interactive:
                    if not self.io.prompt_to_continue(f"Remove module"):
                        continue
                    self.stclc_rmfile(mod['modinstname'])
            if mod['name'] in mod_list:
                LOGGER.error(f"The module {mod['name']} is defined multiple times.")
            else:
                mod_list.append(mod['name'])
        if not mods:
            LOGGER.error("No Design Sync modules found.")
            return True
        if not os.environ["SYNC_DEVAREA_TOP"] in mod_list:
            LOGGER.error(f'The top container module {os.environ["SYNC_DEVAREA_TOP"]} was not found.')
            return True
        return False

    def diag_check_bad_sitr_module(self, mod: str, interactive: bool = True) -> bool:
        """if the status of the module is bad, then fix it up, return True if a fix was done"""
        if self.sitr_mods[mod]['status'] == "NA" or self.sitr_mods[mod]['selector'][0].isdigit():
            if interactive:
                if not self.io.prompt_to_continue(f"Restore the {mod} module"):
                    return False
                LOGGER.info(f"Restoring {mod} to version {self.sitr_mods[mod]['baseline']}")
                self.stclc_update_module(mod, self.sitr_mods[mod]["baseline"])
                return True
        return False

    def diag_check_for_update_mode(self, mod: str, abspath: 'Path', interactive: bool = True) -> bool:
        """for a module in update mode, perform some checks and fix if possible. If fixed return true"""
        branch = self.stclc_get_branch() + ":"
        if not abspath.is_dir():
            LOGGER.error(f"The sitr module {mod} at {self.sitr_mods[mod]['relpath']} not a directory.")
            if interactive:
                if not self.io.prompt_to_continue(f"Restore the {mod} module"):
                    return False
                LOGGER.info(f"Restoring {mod} to version {self.sitr_mods[mod]['baseline']}")
                self.stclc_update_module(mod, self.sitr_mods[mod]["baseline"])
                return True
        if self.sitr_mods[mod]['selector'] != branch:
            LOGGER.error(f"The branch for the module {mod} is {self.sitr_mods[mod]['selector']} not {branch}.")
            if interactive:
                if not self.io.prompt_to_continue(f"Put the {mod} module back onto the {branch} branch"):
                    return False
                self.stclc_update_module(mod, self.sitr_mods[mod]["baseline"], nooverwrite=True)
                return True
        return False

    def diag_check_for_modified_not_locked(self, mod: str, interactive: bool = True) -> None:
        """scan for modified but not locked"""
        files = self.dssc_ls_modules(mod, modified=True)
        mod_files = []
        for file in files:
            if file['fetchedstate'] != 'Lock':
                LOGGER.error(f"In the module {mod}, the file {file['name']} is modified but not locked ({file['fetchedstate']}).")
                mod_files.append(file)
        if mod_files and interactive:
            if self.io.prompt_to_continue(f"File a JIRA with dmrfa.help"):
                # TODO - open a JIRA
                print("Not supported yet")

    def diag_check_for_unmanaged_view(self, relpath: 'Path', abspath: 'Path', interactive: bool = True) -> bool:
        """Scan for unmanaged cadence views with contents that are symlinks"""
        files = self.dssc_ls_modules(relpath, unmanaged=True)
        for file in files:
            if file['name'].endswith('.sync.cds'):
                path = abspath / file['name'][:-9]
                for item in path.iterdir():
                    if item.endswith('.oa-') or item.endswith('.oa%'):
                        LOGGER.error(f"Bad file found in cadence view ({item}).")
                        if interactive and self.io.prompt_to_continue(f"Remove the file"):
                            item.unlink()
                    elif item.is_symlink():
                        LOGGER.error(f"The view {file['name']} is unmanaged but has a symlink ({item}).")
                        # TODO - should fix this

    def diag_get_dirlist(self, path: 'Path') -> List['Path']:
        """Return a list of directories below the specified starting path"""
        dirlist = []
        if path.is_dir():
            dirlist.append(path)
            for item in path.iterdir():
                if item.is_dir():
                    dirlist.extend(self.diag_get_dirlist(item))
        return dirlist

    def diag_check_for_permissions(self, abspath: 'Path', interactive: bool = True) -> bool:
        """Scan for bad permissions on directories"""
        import stat

        exp_gid = Path(os.environ['SYNC_DEVAREA_DIR']).stat().st_gid
        for dir in self.diag_get_dirlist(abspath):
            if not dir.stat().st_mode & stat.S_IWGRP:
                LOGGER.error(f"The directory {dir} is not group writable.")
                # TODO - should fix this
            if not dir.stat().st_mode & stat.S_IRGRP:
                LOGGER.error(f"The directory {dir} is not group readable.")
                # TODO - should fix this
            if not dir.stat().st_mode & stat.S_ISGID:
                LOGGER.error(f"The directory {dir} does not have the group sticky bit set.")
                # TODO - should fix this

    def diag_fix_up_overlaps(self, overlaps: List, relpath: 'Path', interactive: bool = True) -> None:
        """get a list of files that are unmanaged and overlap with a managed version and fix up"""
        for file in overlaps:
            path = relpath / file
            LOGGER.error(f"The file {relpath / file} is unmanaged, but a managed version exists in the vault.")
            if interactive:
                if self.io.prompt_to_continue(f"Remove the version in the workspace and populate the version in the vault"):
                    self.stclc_rmfile(relpath / file)
                    self.stclc_check_out(relpath / file, locked=False)
                elif self.io.prompt_to_continue(f"Check in the version in the workspace and overwrite the version in the vault"):
                    self.stclc_check_in(str(realpath / file), "Overwrite with unmanaged version", args="-new -noiflock -skip")

    def diag_parse_pop_logfile(self, fname: 'Path', relpath: 'Path', interactive: bool = True) -> None:
        """parse a logfile from populate and fix issues and report errors"""
        contents = fname.read_text()
        overlap_def = re.compile(r'.*%0/(\S+)\s+:\s+Error: File Overlaps with Existing Unmanaged Object or Folder')
        file_def = re.compile(r'ERROR: file://(\S+)')
        target_def = re.compile(r'is already associated with target')
        overlaps = []
        errors = []
        parse = False
        for line in contents.splitlines():
            if "WARNINGS and FAILURES LISTING" in line:
                parse = True
            if not parse:
                continue
            # scan for the message for an overlapping unmanaged file
            match = overlap_def.match(line)
            if match:
                overlaps.append(match.group(1))
                continue
            # scan for the message that defines a file that has an error
            match = file_def.match(line)
            if match:
                file = match.group(1)
                continue
            # scan for the message that shows an Href population problem
            match = target_def.match(line)
            if match:
                LOGGER.error(f"Cannot update the Href at {file}")
                if interactive:
                    if not self.io.prompt_to_continue(f"Remove the Href"):
                        continue
                self.stclc_rmfolder(file)
                # TODO - need to repopulate?
                continue
            if 'Error:' in line :
                errors.append(line)
            elif 'Failed' in line :
                errors.append(line)
        self.diag_fix_up_overlaps(overlaps, relpath)
        if errors:
            for err in errors:
                LOGGER.error(err)
            if interactive and self.io.prompt_to_continue(f"File a JIRA with dmrfa.help"):
                # TODO - open a JIRA
                print("Not supported yet")

    def diag_check_pop_module(self, mod: str, relpath: 'Path', interactive: bool = True) -> None:
        """populate the module and check for errors in the logfile"""
        if interactive:
            if not self.io.prompt_to_continue(f"Populate the {mod} module"):
                return
        fname = Path(tempfile.gettempdir()) / next(tempfile._get_candidate_names())
        status = self.stclc_populate(mod, args=f"-log {fname}")
        LOGGER.info(f"Population complete. Logfile = {fname}, status = {status}")
        if not fname.exists():
            LOGGER.info(f"The output logfile {fname} was not created")
            return
        self.diag_parse_pop_logfile(fname, relpath, interactive)

    def diag_check_for_sync_module(self, mod: str, interactive: bool = True) -> bool:
        """check modules that are in-sync and make sure they are cached"""
        #if not mod == 'SIM_DATA' and not abspath.is_symlink():
        #    LOGGER.warn(f"The sitr module {mod} at {self.sitr_mods[mod]['relpath']} not a symlink.")
            #if interactive:
            #    # TODO - check the mcache
            #    if not self.io.prompt_to_continue(f"Restore the {mod} module"):
            #        continue
            #    LOGGER.info(f"Restoring {mod} to version {self.sitr_mods[mod]['baseline']}")
            #    self.stclc_update_module(mod, self.sitr_mods[mod]["baseline"])

    def diag(self, interactive: bool = True, do_pop: bool = False, do_scan: bool = False, do_perf: bool = False) -> bool:
        """Run diagnostics on the modules specified"""
        if self.diag_basic_checks():
            return True
        if self.diag_module_checks(interactive):
            return True

        # Scan through the specified modules
        for mod in self.modules:
            if self.diag_check_bad_sitr_module(mod, interactive):
                continue
            elif self.sitr_mods[mod]['status'] == "Update mode":
                relpath = Path(self.sitr_mods[mod]['relpath'])
                abspath = Path(os.environ["DSGN_PROJ"]) / relpath
                if self.diag_check_for_update_mode(mod, abspath, interactive):
                    continue
                if do_scan:
                    LOGGER.info(f"Scanning the module {mod}.")
                    self.diag_check_for_modified_not_locked(mod, interactive)
                    self.diag_check_for_unmanaged_view(relpath, abspath, interactive)
                    self.diag_check_for_permissions(abspath, interactive)
                if do_pop:
                    self.diag_check_pop_module(mod, relpath, interactive)
            else:
                self.diag_check_for_sync_module(mod, interactive)

    def wtf_set_dev_dir(self):
        self.force_version(self.dev_dir)

    def initial_setup(self):
        self.dump_dss_logfile_to_log()
        self.run_cdws()

    def jira(self, subject: str, comment: str, log_file: Path, email: str) -> int:
        """
        Send jira email with subject and comment and attachment log_file
        """
        content = dict(comment=comment)
        return self.email_command_output(
            email=email,
            subject=subject,
            content=content,
            command_template="JIRA_ticket",
            attachment=log_file,
        )


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
    if args.directory:
        start_dir = args.directory
    else:
        start_dir = Path.cwd()
    print(f"start dir = {start_dir}")
    import Process

    wtf = Wtf_dm()
    dm_shell = Process.Process()
    wtf.configure_shell(dm_shell)
    with dm_shell.run_shell():
        print("Waiting for DM shell")
        if not dm_shell.wait_for_shell():
            print("Timeout waiting for DM shell")
        if args.interactive:
            import IPython  # type: ignore

            IPython.embed()  # jump to ipython shell


if __name__ == "__main__":
    main()
