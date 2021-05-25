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
from textwrap import dedent
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import log

LOGGER = log.getLogger(__name__)

import dm


class Sitar_dm(dm.Dsync_dm):
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
        self.workspace_type = "Design"

    ###############################################
    # Basic methods to manipulate data
    ###############################################

    def force_integrate_mode(self) -> None:
        """set the environment variable to run in Interator mode"""
        self.shell.env["SYNC_DEV_ASSIGNMENT"] = "Integrate"

    def force_version(self, dev_dir: "Path") -> None:
        """set the baseline version of the workspace"""
        config_root = get_sitr_config_root(dev_dir, "Analog")
        self.shell.env["SYNC_PROJECT_CFGDIR"] = str(config_root / "Setting")
        self.shell.env["SYNC_PROJECT_CFGDIR_ROOT"] = str(config_root)
        self.shell.env["SYNC_DEVELOPMENT_DIR"] = str(dev_dir)

    ###############################################
    # Basic calls to the STCLC object
    ###############################################

    def sitr_populate_tag(
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

    def sitr_populate_configs(
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

    def sitr_status(self) -> None:
        """send the sitr status command and stream the output"""
        resp = self.stclc_sitr_status()
        print(f"{resp}")

    def sitr_env(self) -> None:
        """send the sitr env command and stream the output"""
        resp = self.stclc_sitr_env()
        print(f"{resp}")

    def restore_module(self, sitr_mods: List[Dict], modules: List[str]) -> None:
        """put the modules specified back into mcache mode"""
        for mod in modules:
            print(f"Restoring {mod} to version {sitr_mods[mod]['baseline']}")
            self.update_module([mod], sitr_mods[mod]["baseline"])

    def sitr_show_unmanaged(self, sitr_mods: List[Dict], modules: List[str]) -> None:
        """check the unmanaged files in the module and display the files"""
        for mod in modules:
            print(f"Scanning {mod}")
            path = sitr_mods[mod]["relpath"]
            files = self.dssc_ls_modules(path, unmanaged=True)
            if files:
                LOGGER.warn(f"The module {mod} has the following unmanaged files")
                self.io.display_mod_files(files)
                continue

    def get_ws_devname(self) -> str:
        config = self.stclc_get_branch()
        if config == "Trunk":
            config = "v100"
        return f'{os.environ["SYNC_DEVAREA_TOP"]}_{config}'.lower()

    def get_tapeout_tag(self) -> str:
        return f"tapeout_{self.get_ws_devname()}".lower()

    def get_snapshot_tagname(self, tag: str) -> str:
        # Check what branch we're on
        branch = self.stclc_get_branch()
        # On trunk, add REL_ prefix to the tag, otherwise add
        # uppercased branch + "_" as prefix to the tag.
        snap_tag = (
            f"REL_{tag}" if "trunk" in branch.lower() else f"{branch.upper()}_{tag}"
        )
        return snap_tag

    ###############################################
    # Compound calls to the STCLC object
    ###############################################

    def submit_module(
        self, modules: List[str], comment: str, skipcheck: bool = False, email=None
    ) -> bool:
        """submit the specified modules"""

        errors = self.stclc_submit_module(modules, comment, skipcheck)

        if errors:
            for mod in errors:
                LOGGER.error(f"submit module {mod} - {errors[mod]['resp']}")

            if email is not None:
                for mod in vers:
                    ver = (
                        errors[mod]["vers"]
                        .partition(" : Added")[-1]
                        .splitlines()[0]
                        .strip()
                    )
                    content = {
                        "mod": mod,
                        "mods": ",".join(modules),
                        "user": os.environ.get("USER", "nobody"),
                        "ver": ver,
                        "comment": comment,
                        "skipcheck": skipcheck,
                    }
                    self.email_command_output(email, f"submit {mod}", content, "submit")
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

    def create_branch(
        self,
        version: str,
        module_tag: str,
        comment: str,
        email=None,
    ) -> bool:
        """Create a branch of the current top module"""
        url = self.dssc_get_root_url(branch=version)
        if self.stclc_mod_exists(url):
            LOGGER.warn(f"The DSync module ({url}) already esists")
            return False
        if self.stclc_create_branch(
            f'{os.environ["SYNC_DEVAREA_TOP"]}%0', version, comment
        ):
            return True
        if email is not None:
            prj, pr = url.split("%")
            user = getpass.getuser()

            SYNC_DIR = Path(os.environ["SYNC_DEVAREA_DIR"])
            log_dir = SYNC_DIR / f"logs/wtf.py_{user}.log"

            DEVELOPMENT_DIR = Path(os.environ["SYNC_DEVELOPMENT_DIR"])
            sitar_env = self.shell.run_command("sitr env")
            data = [k for k in sitar_env.split("\n") if len(k) > 3 and k != "="]
            data1 = [k for k in data if any(s in k for s in "=")]
            data2 = {k.split("=")[0].strip(): k.split("=")[1].strip() for k in data1}
            content = {
                "DEVELOPMENT_DIR": DEVELOPMENT_DIR,
                "prj": prj,
                "version": version,
                "Container_Workspace": data2["Container Workspace"],
                "user": user,
                "Workspace_URL": data2["sitr_server"],
                "alias": data2["sitr_alias"],
                "comment": comment,
            }
            self.email_command_output(
                email,
                f"New Branch Requested by {user}",
                content,
                "request_branch",
                attachment=log_dir,
            )
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
            url = self.dssc_get_root_url(
                module=branch["module"], version=branch["version"]
            )
            branched_url = self.dssc_get_root_url(
                module=branch["module"], version=f"{version}_v1.1"
            )
            print(f"Branch {url} -> {branched_url}")
            if self.stclc_create_branch(url, version, comment):
                errors = True
            if not self.stclc_mod_exists(branched_url):
                LOGGER.error(f"could not create the sitr module ({branched_url})")
            mod_list[branch["module"]] = {
                "module": branch["module"],
                "tagName": f"{version}_v1.1",
            }
        if errors:
            return {}
        return mod_list

    def sitr_compare(
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

    def sitr_check_tag(
        self, sitr_mods: List[Dict], modules: List[str], tag: str
    ) -> None:
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
            parsed = dm.parse_kv_response(
                "\n".join(resp.splitlines()[1:-1])
            )  # skip first/last line
            if not parsed:
                print(f"No matching files for {tag}")
                continue
            files = dm.get_files(parsed)
            self.io.display_file_versions(files)

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

    def sitr_overlay_tag(
        self, sitr_mods: List[Dict], modules: List[str], tag: str
    ) -> None:
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

    def tag_sch_sym(self, sitr_mods: List[Dict], modules: List[str], tag: str) -> bool:
        """Check to make sure that all sch/sym are checked in, then tag them with the provided tag"""
        args = "-rec -filter +.../schematic.sync.cds,+.../symbol.sync.cds"
        errors = []
        for mod in modules:
            files = self.dssc_ls_modules(mod, locked=True)
            LOGGER.debug(f"results from show checkouts = {files}")
            if files:
                LOGGER.warn(f"The module {mod} has checkouts and cannot be tagged")
                self.io.display_mod_files(files)
                continue
            files = self.dssc_ls_modules(mod, modified=True)
            LOGGER.debug(f"results from show modified = {files}")
            if files:
                LOGGER.warn(f"The module {mod} has modified files and cannot be tagged")
                self.io.display_mod_files(files)
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

    def check_for_submit_errors(self, modules: List[str]) -> bool:
        """check modules for erros that would prevent the submit"""
        errors = set()
        for mod in modules:
            files = self.dssc_ls_modules(mod, locked=True)
            LOGGER.debug(f"results from show checkouts = {files}")
            if files:
                LOGGER.warn(f"The module {mod} has checkouts and cannot be submitted")
                self.io.display_mod_files(files)
                errors.add(mod)
                continue
            # files = self.dssc_ls_modules(mod, modified=True)
            # LOGGER.debug(f"results from show modified = {files}")
            # if files:
            #    LOGGER.warn(
            #        f"The module {mod} has modified files and cannot be submitted"
            #    )
            #    self.io.display_mod_files(files)
            #    errors.add(mod)
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
            args = f'-rec -immutable -comment "{comment}"'
            hrefs = self.dssc_get_hrefs(mod)
            print(f"Hrefs = {hrefs}")
            if hrefs:
                args += f" -filter {','.join([x['relpath'] for x in hrefs])}"
            if self.stclc_tag_files(snap_tag, path, args=args):
                # TODO - raise exception?
                errors.add(mod)
            elif self.snapshot_add_submodules(snap_tag, mod, hrefs, args="-immutable"):
                # TODO - raise exception?
                errors.add(mod)

        if email is not None:
            content = {"modules": ",".join(modules), "tags": tag, "comment": comment}
            self.email_command_output(
                email, "snapshot submit", content, "snapshot_submit"
            )

        if errors:
            LOGGER.warn(
                f"Errors encountered when submitting the {' '.join(errors)} modules"
            )
            return True
        return False

    def make_tapeout_ws(self, sitr_mods: List[Dict], tag: str) -> bool:
        """tag the files and modules with the tapeout tag to create the tapeout ws"""
        for mod in sitr_mods:
            if sitr_mods[mod]["status"] != "Update":
                LOGGER.warn(f"The {mod} module is not in Update mode")
                continue
            relpath = sitr_mods[mod]["relpath"]
            path = Path(os.environ["DSGN_PROJ"]) / relpath
            readme = self.io.make_module_readme(path, f"SITaR module for {mod}")
            if readme.exists():
                resp = self.stclc_get_file_status(str(readme))
                file_status = dm.parse_kv_response(resp)[0]
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
            hrefs = self.dssc_get_hrefs(mod)
            self.snapshot_add_submodules(tag, mod, hrefs)

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

    def sitr_submit(
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
            self.dssc_pop_modules(modules=modules)
            # TODO - do this all of the time?
            self.dssc_checkin_module(modules, comment)
            skipcheck = True
        elif tag:
            # Run snapshot submit only
            return self.snapshot_submit_module(sitr_modules, modules, tag, comment)
        return self.submit_module(modules, comment, skipcheck, email=email)

    def update_module_snapshot(
        self, sitr_mods: List[Dict], modules: List[str], force: bool = False
    ) -> None:
        """update the specified modules and populate the baseline tag"""
        status = False
        for mod in modules:
            if sitr_mods[mod]["status"] != "Update":
                self.update_module([mod])
            tag = sitr_mods[mod]["baseline"]
            status += self.sitr_populate_tag(sitr_mods, [mod], tag, force)
        return status

    def process_sitr_update_list(self, resp_list: List[str]) -> List:
        """get a list of newly submitted modules that can be integrated"""
        resp_str = " ".join([resp.split("\n")[0] for resp in resp_list])
        # TODO - need to support the all switch with multiple submits
        update_list = {}
        kv_resp = dm.parse_kv_response(f"{resp_str}")
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

    def sitr_integrate(
        self, mod_list: List[Dict] = None, nopop: bool = False, email=None
    ) -> bool:
        """run the SITaR integrate"""
        errors = []
        print(f"mod list {mod_list}")
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
        resp = self.stclc_integrate(nopop)
        if resp:
            LOGGER.error(f"integrate {resp}")
            if email is not None:
                content = {"resp": resp, "nopop": nopop}
                self.email_command_output(email, "integrate", content, "integrate")
            return True
        return False

    def sitr_release(
        self,
        comment: str,
        skip_check: bool = False,
        on_server: bool = False,
        email=None,
    ) -> bool:
        """perform the sitr release"""
        resp = self.stclc_sitr_release(comment, skip_check, on_server)
        if resp:
            LOGGER.error(f"release {resp}")
            if email is not None:
                content = {
                    "resp": resp,
                    "comment": comment,
                    "skip_check": skip_check,
                    "on_server": on_server,
                }
                self.email_command_output(email, "release", content, "release")
            return True
        return False

    def get_module_info(self, module: str = "") -> Dict:
        if not module:
            module = "$env(SYNC_DEVAREA_TOP)"
        resp = self.stclc_module_info(module)
        resp = dm.parse_kv_response(resp)
        return resp["actual"]

    def sitr_showstatus(self, modules) -> int:
        """Runs showstatus command for each module (or top module if none given)"""
        if not modules:
            modules = ["$env(SYNC_DEVAREA_TOP)"]
        report = []
        for mod in modules:
            resp = self.stclc_module_status(mod)
            report.extend(
                list(filter(None, map(str.strip, resp.splitlines())))[:-1]
            )  # skip prompt
        errors = self.io.showstatus_report(report)
        if errors:
            errors = "\n".join(errors)
            print(f"\nERRORS:\n\n{errors}\n")

        return 0

    # TODO - move to Email
    def email_command_output(
        self,
        email: str,
        subject: str,
        content: Dict,
        command_template: str,
        attachment: "Path" = None,
    ):
        email_user = getpass.getuser()
        send_email(
            self,
            sender=email_user,
            recipients=[email],
            content=content,
            command_template=command_template,
            attachment=attachment,
        )


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
    # path_of_script = Path(__file__).absolute().parent
    # sys.path.append(str(path_of_script))
    # from Spreadsheet_if import Spreadsheet_xls

    # ss = Spreadsheet_xls()
    # if args.xls:
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
    dssc = Sitar_dm()
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
