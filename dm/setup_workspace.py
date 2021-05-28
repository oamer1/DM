"""script to setup a SITaR based workspace"""

import argparse
import getpass
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Customization
# site = subprocess.check_output(["gvquery","-p" "site"]).rstrip()
# base_path = "/prj/analog/hubble/" + site + "/evalSitarProj"

LOGGER = logging.getLogger(__name__)

# TODO - should this be a class?
class WS_Builder(object):
    """ Class for creating a SITaR based workspace

        Attributes:
            sitr_env: environment variables used for sda
            proj_env: environment variables for the shell
            project_dir: path to the root location of the workspace
            work_dir: path to the working directory for sda
            user_dir: path to the user directory where cadence is launched
            ws_name: name of the sitr workspace
            dsgn_proj: path to the design project location
            container_name: name of the top container
            development_name: name of the specific chip project
            config_root: path for the config location for sda
            test_mode: when true, do not run any actual commands
            role: set to Design or Integrate
    """

    def __init__(self) -> None:
        """Initializer for the workspace builder class"""
        self.sitr_env = {}
        self.proj_env = {}
        self.user_dir = None
        self.ws_name = None
        self.dsgn_proj = None
        self.container_name = None
        self.work_dir = None
        self.development_name = None
        self.project_dir = None
        self.config_root = None
        self.test_mode = False
        self.role = "Design"

    def get_dir_name(integrator: bool = False, name: str = None) -> str:
        """get the dirname for the sitr workspace"""
        user_name = getpass.getuser()
        if name:
            dir_name = name
        elif integrator:
            dir_name = user_name + "_int"
        else:
            dir_name = user_name
        return dir_name

    def get_env(self) -> Dict:
        """get the einvronment for running sda"""
        env = self.sitr_env.copy()
        env.update(self.proj_env)
        return env

    def setup_sitr_role(self, role: str) -> None:
        """set the role for the workspace (Design/Integrate)"""
        self.role = role
        self.sitr_env["SYNC_DEV_ASSIGNMENT"] = role

    def setup_sitr_workdir(self, name: str, shared: bool = False) -> bool:
        """setup the attributes for the workspace"""
        if shared:
            self.work_dir = self.project_dir / "shared"
            self.user_dir = self.work_dir / name
            self.ws_name = f"{self.development_name}_shared"
        else:
            self.work_dir = self.project_dir / name
            self.user_dir = self.work_dir
            self.ws_name = f"{self.development_name}_{name}"

        self.dsgn_proj = self.work_dir / self.container_name
        self.proj_env = {
            "SYNC_DEVAREA_DIR": self.work_dir,
            "PROJECT_DIR": self.project_dir,
            "DSGN_PROJ": self.dsgn_proj,
            "LD_LIBRARY_PATH": "/pkg/qct/software/tcl/8.4.6/lib",
            "QC_CONFIG_DIR": "${DSGN_PROJ}/config",
        }
        # TODO - how to handle when a workspace exists
        # if work_dir.exists():
        #    # TODO - exit if shared
        #    if args.force:
        #        print(f"Overwriting {role} workspace in {work_dir}")
        #    #else:
        #    #    sys.exit(f"The directory {work_dir} already exists. To overwrite use the -f option")
        return self.work_dir.exists()

    def setup_sitr_env(
        self,
        chip_name: str,
        chip_version: str,
        base_path: "Path",
        config_name: str = "Analog",
        dev_dirname: str = None,
    ) -> None:
        """setup the environment variables for creating the workspace using sda"""
        project_name = chip_name + "_" + chip_version
        # Going back to Old format
        development_dir = base_path / project_name.lower()
        # New format only used in Electron
        # if dev_dirname:
        #    development_dir = base_path / Path(dev_dirname)
        # else:
        #    development_dir = base_path / chip_version.lower()
        self.config_root = development_dir / "DesignSync" / "Settings" / config_name
        self.container_name = chip_name.upper()
        self.development_name = project_name.upper()
        self.project_dir = development_dir / "work"
        self.sitr_env = {
            "SYNC_PROJECT_CFGDIR": self.config_root / "Setting",
            "SYNC_PROJECT_CFGDIR_ROOT": self.config_root,
            "SYNC_DEVELOPMENT_DIR": development_dir,
            "SYNC_DEVAREA_TOP": self.container_name,
            "SYNC_DEV_ASSIGNMENT": self.role,
        }

    def run_sda(self, arg_list) -> None:
        """run sda to make the workspace"""
        sub_env = os.environ.copy()
        for var in self.sitr_env:
            sub_env[var] = self.sitr_env[var]

        if self.test_mode:
            LOGGER.info(f"Running subprocess {arg_list}")
        else:
            child = subprocess.Popen(arg_list, env=sub_env)
            exit_code = child.wait()
            # TODO - should throw exception
            if exit_code:
                sys.exit(f"Error encountered when creating workspace {exit_code}")

    def setup_shared_ws(self) -> None:
        """setup the workspace (which is in a different location than the work dir"""
        if self.test_mode:
            LOGGER.info(f"Making the directory {self.user_dir}")
        else:
            self.user_dir.mkdir(exist_ok=True)

        user_dsgn_proj = self.user_dir / self.container_name

        if self.test_mode:
            LOGGER.info(f"Adding symlink to {self.dsgn_proj}")
        else:
            user_dsgn_proj.symlink_to(self.dsgn_proj)

    def setup_source_files(self) -> None:
        """create the files to source for using the workspace"""
        proj_setup = ""
        sh_setup = ""
        for var in self.sitr_env:
            proj_setup += f"setenv {var} {self.sitr_env[var]}\n"
            sh_setup += f"export {var}={self.sitr_env[var]}\n"
        for var in self.proj_env:
            proj_setup += f"setenv {var} {self.proj_env[var]}\n"
            sh_setup += f"export {var}={self.proj_env[var]}\n"

        setup_file = self.user_dir / ".cshrc.project"
        if self.test_mode:
            LOGGER.info(f"Creating {setup_file} = {proj_setup}")
        else:
            setup_file.write_text(proj_setup)

        setup_file = self.user_dir / ".shrc.project"
        if self.test_mode:
            LOGGER.info(f"Creating {setup_file} = {sh_setup}")
        else:
            setup_file.write_text(sh_setup)

    def setup_cds_lib(self) -> None:
        """setup the cds.lib file for launching cadence"""
        cds_file = self.user_dir / "cds.lib"
        cds_file_contents = "SOFTINCLUDE $TECH_DIR/$FOUNDRY/$PROCESS/$TECH_VERSION/qcCadence/inits/cds.lib\n"
        cds_file_contents += f"SOFTINCLUDE ./{self.container_name}/cds.lib.project\n"
        if self.test_mode:
            LOGGER.info(f"Creating {cds_file} = {cds_file_contents}")
        else:
            cds_file.write_text(cds_file_contents)

    def copy_ws_setup_files(self) -> None:
        """copy over files for cadence from the config module"""
        for file in [
            "cdsLibMgrProject.il",
            "hdl.var",
            "hed.env",
            "hierEditor.env",
            "run_ams",
        ]:
            src = self.dsgn_proj / "config" / file
            if src.exists() and not self.test_mode:
                if self.test_mode:
                    LOGGER.info(f"Copying {src}")
                else:
                    shutil.copy2(src, self.user_dir)
            else:
                LOGGER.warn(f"Cannot access {src}")

    def setup_ws(self) -> None:
        """call the different methods to setup a workspace after sda has been called"""
        self.setup_source_files()
        self.setup_cds_lib()
        self.copy_ws_setup_files()

    def create_shared_ws(self, dir_name: str) -> None:
        """create the shared workspace"""
        # TODO - handle the return code
        self.setup_sitr_workdir(dir_name, True)
        # TODO - should make sure that this is not integrator
        LOGGER.info(f"Creating the shared workspace {self.ws_name} in {self.work_dir}")
        arg_list = [
            "/pkg/icetools/bin/sda",
            "mk",
            self.ws_name,
            self.development_name,
            "-assignment",
            self.role,
            "-shared",
            "-path",
            self.work_dir,
        ]
        self.run_sda(arg_list)
        # TODO - put modules into update mode
        self.setup_shared_ws()
        self.setup_ws()

    def join_shared_ws(self, dir_name: str) -> None:
        """call sda so that the user joins the shared workspace"""
        # TODO - handle the return code
        self.setup_sitr_workdir(dir_name, True)
        LOGGER.info(f"Joining the shared workspace {self.ws_name} in {self.work_dir}")
        arg_list = [
            "/pkg/icetools/bin/sda",
            "join",
            self.ws_name,
            "-development",
            self.development_name,
        ]
        self.run_sda(arg_list)
        self.setup_shared_ws()
        self.setup_ws()

    def create_ws(self, dir_name: str) -> None:
        """create an individual workspace"""
        if self.setup_sitr_workdir(dir_name):
            LOGGER.info(
                f"The workspace {self.ws_name} already exists in {self.work_dir}"
            )
        else:
            LOGGER.info(f"Populating the workspace {self.ws_name} in {self.work_dir}")
            arg_list = [
                "/pkg/icetools/bin/sda",
                "mk",
                self.ws_name,
                self.development_name,
                "-assignment",
                self.role,
                "-path",
                self.work_dir,
            ]
            self.run_sda(arg_list)
            self.setup_ws()


def main():
    parser = argparse.ArgumentParser(
        description="Create a SITaR workspace for the current project.",
        epilog="Create and populate a new SITaR workspace.",
        add_help=True,
        argument_default=None,  # Global argument default
        usage=__doc__,
    )
    parser.add_argument(
        "-n", "--name", type=str, help="Specify the name of the workspace"
    )
    parser.add_argument(
        "-N", "--no_action", action="store_true", help="Do not create the workspace"
    )
    parser.add_argument(
        "-s", "--shared", action="store_true", help="Join the shared workspace"
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force populate if the directory exists",
    )
    parser.add_argument(
        "-m",
        "--make_shared",
        action="store_true",
        help="Make a shared workspace for a project",
    )
    parser.add_argument(
        "-i", "--integrator", action="store_true", help="create an integrator workspace"
    )
    parser.add_argument(
        "-I", "--interactive", action="store_true", help="enable an interactive session"
    )
    parser.add_argument(
        "-T", "--test_mode", action="store_true", help="enable test mode"
    )
    parser.add_argument("-t", "--test", action="store_true", help="run the doctest")
    parser.add_argument(
        "-d", "--debug", action="store_true", help="enable debug outputs"
    )

    args = parser.parse_args()

    ws = WS_Builder()

    if args.test_mode:
        ws.test_mode = True

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    # TODO - hard coded data
    chip_name = "Caster"
    chip_version = "v100"
    server = "sync://ds-caster-lnx-01:3330"
    base_path = Path("/prj/analog/wanip/sec14ff/chips/caster")
    config_name = "Caster_Analog"
    ws.setup_sitr_env(chip_name, chip_version, base_path, config_name)

    if args.make_shared or args.shared:
        role = "Shared"
    elif args.integrator:
        role = "Integrate"
    else:
        role = "Design"
    ws.setup_sitr_role(role)

    if not ws.config_root.exists():
        sys.exit(f"Cannot access the config root directory ({ws.config_root})")

    dir_name = ws.get_dir_name(args.integrator, args.name)

    if not args.no_action:
        if args.make_shared:
            ws.create_shared_ws(dir_name)
        elif args.shared:
            ws.join_shared_ws(dir_name)
        else:
            ws.create_ws(dir_name)

    if args.test:
        import doctest

        doctest.testmod()

    if args.interactive:
        import IPython  # type: ignore

        IPython.embed()  # jump to ipython shell

    if not args.no_action:
        if not ws.work_dir.exists():
            sys.exit(f"The directory {ws.work_dir} was not created.")

        # TODO - setup scratch pointer
        print(f"The workspace {ws.user_dir} is ready")


if __name__ == "__main__":
    main()
