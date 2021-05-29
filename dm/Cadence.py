#!/pkg/qct/software/python/3.6.0/bin/python

""" Contains the modules for creating Cadence Libraries

    import Cadence
    cad = Cadence(cwd=start_dir)
    with cad.run_shell():
        print("Waiting for Cadence shell")
        module = "rxsig"
        libs = "rxbbf rxfe"
        (cds_lib_files, libs_to_add) = check_libraries(cad, module, libs)
        if cds_lib_files:
            print(f"Need to check out these files {cds_lib_files}")
        else:
            cad.make_cadence_libs(libs_to_add)
"""

import argparse
import os
import logging
from typing import List, Dict, Optional, Tuple, Sequence, Any
from pathlib import Path
from contextlib import contextmanager

try:
    from dm import *
except ImportError:
    try:
        import Process
        import Dsync
    except ImportError:
        pass

LOGGER = logging.getLogger(__name__)


def checkout_cds_files(dm: "Dsync", files: List) -> bool:
    """Given a list of cds.lib files, check them out for edit and ensure they are writable"""
    for file in files:
        dm.stclc_check_out(file)
        if not os.access(file, os.W_OK):
            LOGGER.error(f"Cannot write to the file {file}")
            return False
    return True


def checkin_files(dm: "Dsync", libs_to_add: List) -> None:
    comment = "Creating the libraries"
    files = ""
    for (cds_file, lib_name) in libs_to_add:
        files += " " + str(cds_file)
        files += " " + str(cds_file.parent / lib_name)
        comment += " " + lib_name
    dm.stclc_check_in(files, comment)


def get_cds_file(mod_path: "Path", lib: str) -> "Path":
    if lib.upper().endswith("_SIM"):
        return mod_path / "sim_libs" / "cds.lib.sim_libs"
    return mod_path / "design_libs" / "cds.lib.design_libs"


# TODO - should this be a class? Use dependency injection instead of extending
class Cadence(object):
    def __init__(self, cwd: str = None, test_mode: bool = False) -> None:
        self.dsgn_proj = None
        self.start_dir = Path(cwd) if cwd else Path.cwd()
        self.dsgn_proj = self.get_dsgn_proj()
        self.test_mode = test_mode

    def configure_shell(self, shell: "Process") -> None:
        shell.command = "/pkg/icetools/bin/virtuoso -no_ver_check -qc_memory 6000 -qc_64bit -qc_queue interactive -nograph"
        shell.prompt = "CIW>"
        shell.start_cmd = 'setPrompts("CIW> " "<%d> CIW> ")'
        shell.end_cmd = "exit"
        shell.init_timeout = 30000
        shell.timeout = 8
        shell.cwd = self.start_dir
        self.shell = shell

    def check_libraries(self, module: str, libs: List[str]) -> Tuple[List, List]:
        """Given a SITaR module and list of libraries, return a list of cds.lib files to check out and libs"""
        mod_path = self.find_module(module)
        files_to_checkout = []
        libs_to_add = []
        for lib in libs:
            cds_file = get_cds_file(mod_path, lib)
            if not cds_file.parent.exists():
                cds_file.parent.mkdir()
            if not cds_file.exists():
                cds_file.touch()
            elif not os.access(cds_file, os.W_OK):
                files_to_checkout.append(cds_file)
            LOGGER.info(f"Creating the library {lib} in {cds_file}")
            libs_to_add.append(tuple([cds_file, lib]))
        return (files_to_checkout, libs_to_add)

    def find_module(self, mod: str = "") -> "Path":
        for dir in self.dsgn_proj.iterdir():
            if Path(dir / mod.lower()).exists():
                return dir / mod.lower()
        LOGGER.error(f"Cannot find the module {mod}")
        return None

    def get_dsgn_proj(self) -> None:
        """Try to find the Design Project folder (start of managed area)"""
        if "DSGN_PROJ" in os.environ:
            return Path(os.environ["DSGN_PROJ"])

        for dir in self.start_dir.iterdir():
            if Path(dir / "cds.lib.project").exists():
                return dir
        return None

    def make_cadence_libs(self, libs_to_add: List[Tuple]) -> None:
        """Given a list of new libraires and cds_libfiles, create the new libraries"""
        for (cds_file, lib_name) in libs_to_add:
            self.make_cadence_lib(cds_file, lib_name)

    def make_cadence_lib(self, cds_file: "Path", lib: str) -> None:
        # TODO - check resp?
        resp = self.shell.run_command(
            f'changeWorkingDir("{cds_file.parent.resolve()}")'
        )
        resp = self.shell.run_command(f'ddSetForcedLib("{cds_file.resolve()}")')
        resp = self.shell.run_command(
            f'qcCreateLib("{lib}" "./{lib}" qcVars->technologyLib qcVars->process "sync")'
        )
        resp = self.shell.run_command(f'qcSetDMTYPEForLib("./{lib}")')


def main():
    """Main routine that is invoked when you run the script"""
    parser = argparse.ArgumentParser(
        description="Script to automatically create Cadence Libraries.",
        add_help=True,
        argument_default=None,  # Global argument default
    )
    parser.add_argument(
        "libs",
        metavar="Cadence Libs",
        type=str,
        nargs="+",
        help="List of library names",
    )
    parser.add_argument(
        "-m", "--module", required=True, help="Specify the destination module"
    )
    parser.add_argument(
        "-w", "--workspace", help="Specify the workspace where to launch cadence"
    )
    parser.add_argument(
        "-d", "--debug", action="store_true", help="enable debug outputs"
    )
    parser.add_argument(
        "-l", "--lib", action="store_true", help="Create the specified libraries"
    )
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

    if args.test:
        import doctest

        doctest.testmod()

    # start_dir = "/prj/analog/blaster/sandiego/chips/blaster/blaster_v100/work/jcoates"
    # start_dir = "/prj/analog/wanip/sec14ff/chips/caster/caster_v100/work/jcoates"

    cad = Cadence(cwd=args.workspace, test_mode=args.test_mode)
    # TODO - need to check to make sure dsgn_proj is defined
    dm = Dsync.Dsync(cwd=cad.dsgn_proj, test_mode=args.test_mode)

    dm_shell = Process.Process()
    dm.configure_shell(dm_shell)
    with dm_shell.run_shell():
        ciw_shell = Process.Process()
        cad.configure_shell(ciw_shell)
        with ciw_shell.run_shell():
            # TODO - need a try-catch block
            (files_to_checkout, libs_to_add) = cad.check_libraries(
                args.module, args.libs
            )

            if Dsync.prompt_to_continue():
                print("Waiting for DM shell")
                if not dm_shell.wait_for_shell():
                    print("Timeout waiting for DM shell")
                    # TODO - what to do here?

                print("Waiting for Cadence shell")
                if not ciw_shell.wait_for_shell():
                    print("Timeout waiting for Cadence shell")
                    # TODO - what to do here?

                # Check out all of the needed files (if any)
                if checkout_cds_files(dm, files_to_checkout):
                    # Make all of the libraries
                    cad.make_cadence_libs(libs_to_add)
                    # TODO - prompt for check-in
                    if Dsync.prompt_to_continue("Check in files"):
                        checkin_files(dm, libs_to_add)
                # TODO - report error?

            if args.interactive:
                import IPython  # type: ignore

                IPython.embed()  # jump to ipython shell


if __name__ == "__main__":
    main()
