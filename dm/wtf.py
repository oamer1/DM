#! /pkg/qct/software/python/3.6.0/bin/python
"""
Supports running SITaR commands via a DM shell.
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Dict, Iterable, Optional

SCRIPT_NAME = Path(__file__).name
LOG_DIR = Path(os.environ.get("SYNC_DEVAREA_DIR", Path.home())) / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "{script}_{user}.log".format(
    script=SCRIPT_NAME, user=os.environ.get("USER", "nobody")
)
os.environ.setdefault("LOGFILE_NAME", str(LOG_FILE))


try:
    import log  # isort: skip
except ImportError:
    try:
        pwd = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, pwd + '/../log')
        import log
    except ImportError:
        pass


try:
    from dm import *
except ImportError:
    try:
        pwd = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, pwd + '/../dm')
        from dm import *
    except ImportError:
        pass
#from dm import *  # isort:skip

LOGGER = log.getLogger(__name__)


def command(*, setup: callable = None):
    """
    Decorator for functions implementing commands inside of the virtualenv.
    """

    def inner(func):
        @wraps(func)
        def wrapped(dm, args: argparse.Namespace):
            return func(dm, args)

        wrapped.__cmd__ = True
        wrapped.__setup__ = setup
        return wrapped

    return inner


def add_command_parser(
    commands: argparse.ArgumentParser, func_name: str, func: callable
) -> argparse.ArgumentParser:
    command_parser = commands.add_parser(
        func_name, help=func.__doc__, description=func.__doc__
    )
    command_parser.set_defaults(func=func)
    return command_parser


def run_doctests(run=False):
    """Runs docstring-embedded tests if `run` is True."""
    if run:
        import doctest

        doctest.testmod()


def get_start_dir(directory=None):
    """Returns the given `directory` or cwd if not given."""
    return directory or Path.cwd()


def running_inside_dmsh():
    """Returns True if running inside a DMSH shell."""
    if "DM_WORKSPACE_NAME" in os.environ:
        LOGGER.error(
            "This script cannot be run from a DMSH shell. "
            "Please run in a different terminal window"
        )
        return True
    return False


def write_mod_versions(mod_list, fname):
    """Write out the module versions for integration"""
    contents = [f"{mod}@{mod_list[mod]['tagName']}\n" for mod in mod_list]
    path = Path(fname)
    path.write_text("".join(contents))


def read_mod_versions(fname):
    """Read in the module versions for integration"""
    f = Path(fname).resolve()
    if not f.exists():
        LOGGER.error(f"Given --integrate file {f!s} NOT found!")
        return []
    select_list = [
        item.split("@") for item in f.read_text().splitlines() if "@" in item
    ]
    return {item[0]: {"module": item[0], "tagName": item[1]} for item in select_list}


def setup_dmsh(start_dir, test_mode, bsub_mode=False):
    """
    Sets up DMSH and prepares to run it, returning the configured dm and
    dm_shell."""
    LOGGER.debug(f"start dir = {start_dir}")
    dm = Dsync.Dsync(cwd=start_dir, test_mode=test_mode, bsub_mode=bsub_mode)
    # TODO - this will not work in shared
    root_dir = Dsync.find_sitr_root_dir(start_dir)
    # TODO - what about a shared ws?
    env_dir = Path(os.environ["SYNC_DEVAREA_DIR"])
    # TODO - this does not work from the config directory
    if root_dir != env_dir:
        LOGGER.warn(
            f"Running in a different workspace {root_dir}, but environment is setup for {env_dir}"
        )
    data_reg = env_dir / "data.reg"
    if data_reg.exists():
        LOGGER.warn("Removing the data.reg file " "which interferes with DesignSync")
        data_reg.unlink()
    role = os.environ["SYNC_DEV_ASSIGNMENT"]
    dm.workspace_type = "Design"
    if role == "Shared":
        if env_dir.stem.startswith("tapeout"):
            dm.workspace_type = "Tapeout"
            dm.tapeout_tag = env_dir.stem
        elif env_dir.stem.startswith("shared"):
            dm.workspace_type = "Shared"
    elif role == "Integrate":
        dm.workspace_type = role
    dm_shell = Process.Process()
    dm.configure_shell(dm_shell)
    return dm, dm_shell


def get_comment(
    is_checkin,
    is_submit,
    is_snapshot,
    is_int_release,
    is_release,
    is_mk_release,
    is_request_branch,
    is_mk_branch,
    comment,
):
    """
    For checkin, submit, snapshot, or release commands, ensure a comment is given
    or ask for one, and return it. Otherwise returns None.
    """
    if (
        is_checkin
        or is_submit
        or is_snapshot
        or is_int_release
        or is_release
        or is_mk_release
        or is_request_branch
        or is_mk_branch
    ):
        # TODO - make sure that the role is design
        if not comment:
            comment = input("Please provide a comment: ")
        return comment


def wait_for_shell_with_timeout(shell, shell_type: str = "DM"):
    """Waits for shell to start up to the timeout."""
    LOGGER.info(f"Waiting for {shell_type} shell")
    if not shell.wait_for_shell():
        LOGGER.error(f"Timeout waiting for {shell_type} shell")


def run_cdws(dm):
    """Runs cdws commands returns the response."""
    # container = dm.current_module()
    return dm.shell.run_command("cdws")


def get_sitr_modules(
    dm,
    given_mods,
    is_update,
    is_update_snap,
    is_pop_modules,
    is_pop_tag,
    is_checkin,
    is_tag_sch,
    is_show_checkouts,
    is_submit,
    is_snapshot,
):
    """
    Returns all and the effective modules that are available (or explicitly
    given) depending on the command.
    """
    sitr_mods = dm.get_sitr_modules()
    if not given_mods:
        given_mods = list(sitr_mods.keys())
    modules = []
    for mod in given_mods:
        if mod not in sitr_mods:
            LOGGER.warn(f"The module {mod} does not exist in this workspace")
            continue
        if "status" not in sitr_mods[mod]:
            continue
        LOGGER.debug(
            f"mod = {mod}, "
            f"path = {sitr_mods[mod]['relpath']}, "
            f"status = {sitr_mods[mod]['status']}"
        )
        if not (is_update or is_update_snap) and (
            is_pop_modules
            or is_pop_tag
            or is_checkin
            or is_tag_sch
            or is_show_checkouts
            or is_submit
            or is_snapshot
        ):
            if sitr_mods[mod]["status"] != "Update":
                LOGGER.warn(f"The module {mod} is not in update mode")
                continue
        modules.append(mod)
    return sitr_mods, modules


def run_update_snap(dm, sitr_mods, modules, run=False, is_force=False):
    """Runs update_snap command if `run` is True."""
    # TODO: Remove once refactored into a command
    if run:
        dm.update_module_snapshot(sitr_mods, modules, is_force)


def run_restore(dm, sitr_mods, modules, run=False):
    """Runs restore command if `run` is True."""
    # TODO: Remove once restore command is tested and working
    if run:
        dm.restore_module(sitr_mods, modules)


def run_pop_modules(dm, modules, run=False, is_force=False):
    """Runs pop_modules command if `run` is True."""
    # TODO: Remove once refactored into a command
    if run:
        dm.pop_sitr_modules(is_force, modules)


def run_pop_tag(dm, sitr_mods, modules, tag, is_force=False):
    """Runs pop_tag command if `tag` is non-empty."""
    # TODO: Remove once refactored into a command
    if tag:
        dm.populate_tag(sitr_mods, modules, tag, is_force)


def run_checkin(dm, modules, comment, run=False):
    """Runs checkin command if `run` is True."""
    # TODO: Remove once refactored into a command
    if run:
        dm.checkin_module(modules, comment)


def run_tag_sch(dm, sitr_mods, modules, tag):
    """Runs tag_sch command if `tag` is non-empty."""
    # TODO: Remove once refactored into a command
    if tag:
        dm.tag_sch_sym(sitr_mods, modules, tag)


def run_lookup(dm, modules, run=False):
    """Run lookup command if `run` is True."""
    # TODO: Remove once refactored into a command
    if run:
        mod_list = dm.get_sitr_update_list(modules)
        if not mod_list:
            LOGGER.warn("No new submits to integrate")
        else:
            dm.display_mod_list(mod_list)


def setup_populate_args(parser):
    """handle the command line arguments for pop_modules"""
    parser.add_argument("-f,--force", action="store_true", help="Force populate")


@command(setup=setup_populate_args)
def populate(dm, args: argparse.Namespace) -> int:
    """Populate a SITaR workspace"""
    if dm.workspace_type == "Tapeout":
        dm.setup_tapeout_ws(args.mods, dm.tapeout_tag)
        dm.pop_sitr_modules(args.mods)
    else:
        if dm.workspace_type == "Shared":
            dm.setup_shared_ws(args.mods)
        dm.stclc_populate_workspace(args.force)
    return 0


@command(setup=setup_populate_args)
def pop_modules(dm, args: argparse.Namespace) -> int:
    """Populate all modules in update mode in the SITaR workspace"""
    if args.module:
        mod_list = args.module
    else:
        mod_list = args.mods
    dm.pop_sitr_modules(args.force, mod_list)
    return 0


def setup_populate_tag_args(parser):
    """handle the command line arguments for populate_tag"""
    parser.add_argument("-f,--force", action="store_true", help="Force populate")
    parser.add_argument(
        "-n",
        "--tag",
        help="Specify the tag(s) to populate",
        required=True,
        metavar="TAG",
        type=str,
        default="",
    )


@command(setup=setup_populate_tag_args)
def populate_tag(dm, args: argparse.Namespace) -> int:
    """Populate a tag in a SITaR workspace when modules are in update mode"""
    dm.populate_tag(args.mods, args.module, args.tag, args.force)
    return 0


def setup_pop_latest_args(parser):
    """handle the command line arguments for populate_latest"""
    parser.add_argument(
        "-n",
        "--tag",
        help="Specify the tag(s) to populate",
        metavar="TAG",
        type=str,
        default="",
    )
    parser.add_argument("-f,--force", action="store_true", help="Force populate")


@command(setup=setup_pop_latest_args)
def pop_latest(dm, args: argparse.Namespace) -> int:
    """Populate a SITaR workspace for the flat release flow"""
    if dm.workspace_type == "Tapeout":
        dm.setup_tapeout_ws(args.mods, dm.tapeout_tag, args.force)
        dm.pop_sitr_modules(args.mods)
    elif dm.workspace_type == "Shared":
        dm.setup_shared_ws(args.mods)
        dm.stclc_populate_workspace(args.force)
    else:
        dm.stclc_populate_workspace(args.force)
        if args.tag:
            dm.populate_tag(args.mods, args.mods, args.tag)
        mod_list = dm.get_sitr_update_list(args.mods)
        dm.populate_configs(args.mods, mod_list)
        # TODO - run voos
        # TODO - send email(check submit command, if --noemail option given then, no email, by default send email)
    return 0


@command()
def status(dm, args: argparse.Namespace) -> int:
    """Perform a SITaR status"""
    dm.sitr_status()
    return 0


def setup_update_args(parser):
    """handle the command line arguments for update"""
    parser.add_argument(
        "-c",
        "--config",
        help="Specify the config version to populate",
        metavar="VERSION",
        type=str,
        default="",
    )
    parser.add_argument(
        "-D",
        "--delta",
        help="Update the module and populate the baseline config",
        action="store_true",
        default=False,
    )


@command(setup=setup_update_args)
def update(dm, args: argparse.Namespace) -> int:
    """Set module(s) (or all modules) in update mode"""
    # TODO - do we need the force switch? Or no overwrite?
    if args.delta:
        dm.update_module_snapshot(args.mods, args.module)
    else:
        dm.update_module(args.module, args.config)
    return 0


@command()
def restore(dm, args: argparse.Namespace) -> int:
    """Restore the specified module to the latest baseline"""
    # FIXME: Test if it works
    run_restore(dm, args.mods, args.module, True)
    return 0


@command()
def show_checkouts(dm, args: argparse.Namespace) -> int:
    """Scan for checkouts in the module"""
    dm.show_checkouts(args.module)
    return 0


@command()
def show_locks(dm, args: argparse.Namespace) -> int:
    """Show the files locked in the module module"""
    dm.show_locks(args.module)
    return 0


@command()
def show_unmanaged(dm, args: argparse.Namespace) -> int:
    """Show unmanaged files in the specified modules"""
    dm.show_unmanaged(args.mods, args.module)
    return 0


@command()
def showstatus(dm, args: argparse.Namespace) -> int:
    """Runs showstatus command for the modules"""
    # When no explicit modules are given, pass none.
    modules = args.module if args.module_given else []
    dm.showstatus(modules)
    return 0


def setup_showhrefs(parser):
    """handle the command line arguments for showhrefs"""
    parser.add_argument(
        "-s",
        "--submod",
        help="Specify the submodule to display",
        metavar="SUBMODULE",
        type=str,
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Export to specified XLS or CSV file",
        metavar="FILENAME",
        type=str,
        default="",
    )


@command(setup=setup_showhrefs)
def showhrefs(dm, args: argparse.Namespace) -> int:
    """Show the Hrefs for the specified modules"""
    href_args = (args.module if args.module_given else [], args.submod)
    dm.show_module_hrefs(*href_args, args.output)
    return 0


def setup_updatehrefs_args(parser):
    """handle the command line arguments for updatehrefs"""
    parser.add_argument(
        "-i",
        "--input",
        type=str,
        metavar="FILENAME",
        help="XLS or CSV file with hrefs to use",
    )
    parser.add_argument(
        "-S",
        "--submod",
        type=str,
        metavar="SUBMODULE",
        help="Submodule to filter on",
        default=None,
    )


@command(setup=setup_updatehrefs_args)
def updatehrefs(dm, args: argparse.Namespace) -> int:
    """Update Hrefs from a XLS file, optionally filtering by submodule"""
    dm.update_hrefs(args.submod, args.input)
    return 0


def setup_check_tag_args(parser):
    """handle the command line arguments for check tag"""
    parser.add_argument(
        "-n", "--tag", help="Specify the tagname", metavar="TAG", type=str
    )


@command(setup=setup_check_tag_args)
def check_tag(dm, args: argparse.Namespace) -> int:
    """Checks for the TAG for files in MODULE"""
    tag = args.tag
    return dm.check_tag(args.mods, args.module, tag)


def setup_compare_args(parser):
    """handle the command line arguments for compare"""
    parser.add_argument(
        "-n", "--tag", help="Specify the tagname to compare", metavar="TAG", type=str
    )
    parser.add_argument("-t", "--trunk", help="Compare vs Trunk", action="store_true")
    parser.add_argument(
        "-b", "--baseline", help="Compare vs Baseline", action="store_true"
    )


@command(setup=setup_compare_args)
def compare(dm, args: argparse.Namespace) -> int:
    """Run a compare on the specified MODULES vs Trunk/Version/Tag"""
    return dm.compare(args.mods, args.module, args.tag, args.trunk, args.baseline)


@command()
def vhistory(dm, args: argparse.Namespace) -> int:
    """This command will display the version history for the module"""
    # FIXME: Check which Dsync output parser helpers should be used
    dm.vhistory(args.module)
    return 0


@command(setup=setup_check_tag_args)
def overlay_tag(dm, args: argparse.Namespace) -> int:
    """Overlay the specified tag in the specified modules and check-in"""
    dm.overlay_tag(args.mods, args.module, args.tag)
    return 0


def setup_mk_lib_args(parser):
    """handle the command line arguments for mk_lib"""
    parser.add_argument("mod", type=str, metavar="MODULE", help="Module to operate on")
    parser.add_argument("lib", metavar="LIB", help="Library(ies) to create", nargs="+")


@command(setup=setup_mk_lib_args)
def mk_lib(cad, args: argparse.Namespace) -> int:
    """Create Cadence library(ies) in a module"""
    (files_to_checkout, libs_to_add) = cad.check_libraries(args.mod, args.lib)
    if not libs_to_add:
        LOGGER.warn("No libraries to add")
        return 1
    if Dsync.prompt_to_continue():
        if cad.checkout_files(files_to_checkout):
            cad.make_cadence_libs(libs_to_add)
            if Dsync.prompt_to_continue("Check in files"):
                cad.checkin_libs(libs_to_add)
    return 0


@command()
def setup_ws(dm, args: argparse.Namespace) -> int:
    """Setup a workspace after it has been created"""
    if dm.workspace_type == "Tapeout":
        dm.setup_tapeout_ws(args.mods, dm.tapeout_tag)
    elif dm.workspace_type == "Shared":
        dm.setup_shared_ws(args.mods)
    else:
        dm.stclc_populate_workspace()
    # TODO - send email(check submit command, if --noemail option given then, no email, by default send email)
    return 0


def setup_submit_args(parser):
    """handle the command line arguments for submit"""
    parser.add_argument(
        "-n",
        "--snap",
        help="Perform a snapshot submit",
        metavar="TAG",
        type=str,
        default="",
    )
    parser.add_argument(
        "-p",
        "--pop",
        help="Populate latest then submit",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "-c", "--comment", default=None, help="Provide a comment for the action"
    )
    parser.add_argument("--noemail", action="store_true", help="Do not send email")


@command(setup=setup_submit_args)
def submit(dm, args: argparse.Namespace) -> int:
    """Perform a SITaR submit / snapshot submit"""
    tag = args.snap
    email = None
    if not args.noemail:
        config_dir = Path(os.environ["QC_CONFIG_DIR"])
        fname = config_dir / "project.xml"
        LOGGER.info("Parsing %s to find email to notify...", str(fname))
        email = dm.parse_project_xml(fname)
        LOGGER.info("Using email: %s", email)

    return dm.submit(args.pop, tag, args.mods, args.module, args.comment, email=email)


def setup_mk_tapeout_ws(parser):
    """handle the command line arguments for mk_tapeout_ws"""
    parser.add_argument(
        "-n",
        "--tag",
        help="Specify the tapeout tag to use",
        metavar="TAG",
        type=str,
        default="",
    )


@command(setup=setup_mk_tapeout_ws)
def mk_tapeout_ws(dm, args: argparse.Namespace) -> int:
    """Make the tapeout workspace for the project"""
    tag = dm.get_tapeout_tag()
    if args.tag:
        tag = args.tag.lower()
        if not tag.startswith("tapeout"):
            LOGGER.error("The tag must start with tapeout.")
            return 1
    args.ws_name = tag
    args.dev_name = dm.get_ws_devname()
    dm.make_tapeout_ws(args.mods, tag)
    return 0


def setup_request_branch_args(parser):
    """handle the command line arguments for request_branch"""
    parser.add_argument(
        "-v",
        "--version",
        required=True,
        help="Specify the version to use for the branch",
        metavar="VER",
        type=str,
    )
    parser.add_argument(
        "-c", "--comment", default=None, help="Provide a comment for the action"
    )


@command(setup=setup_request_branch_args)
def request_branch(dm, args: argparse.Namespace) -> int:
    """Request a branch for the current project"""
    # TODO - should not start up the first shell for this command
    return 0


def setup_mk_branch_args(parser):
    """handle the command line arguments for mk_branch"""
    parser.add_argument(
        "-v",
        "--version",
        required=True,
        help="Specify the version to use for the branch",
        metavar="VER",
        type=str,
    )
    parser.add_argument(
        "-n",
        "--tag",
        help="Specify the tapeout tag for the branch",
        metavar="TAG",
        type=str,
        default="",
    )
    parser.add_argument(
        "-c", "--comment", default=None, help="Provide a comment for the action"
    )
    # TODO - if we cannot set the sitr alias, then we will need to specify the integrate workspace to use


@command(setup=setup_mk_branch_args)
def mk_branch(dm, args: argparse.Namespace) -> int:
    """Make a branch in the current workspace where the tapeout tag is populated"""
    tag = dm.get_tapeout_tag()
    if args.tag:
        tag = args.tag.lower()
        if not tag.startswith("tapeout"):
            LOGGER.error("The tag must start with tapeout.")
            return 1
    url = dm.get_root_url(version=version)
    if not dm.stclc_mod_exists(url):
        LOGGER.error("The top level url ({url}) does not exist.")
        return 2
    if dm.workspace_type == "Tapeout":
        LOGGER.error("Cannot make a branch in a Tapeout workspace.")
        return 3
    dm.stclc_populate_workspace()
    if args.tag:
        dm.populate_tag(args.mods, args.mods, args.tag)
    mod_list = dm.get_sitr_update_list(args.mods)
    dm.populate_configs(args.mods, mod_list)
    args.mod_list = dm.flat_release_submit(args.mods, tag, args.comment)
    if not args.mod_list:
        return 3
    args.version = args.tag
    return 0


def setup_mk_release_args(parser):
    """handle the command line arguments for mk_release"""
    parser.add_argument(
        "-n",
        "--snap",
        help="Specify the snapshot tag for the submit",
        required=True,
        metavar="TAG",
        type=str,
    )
    parser.add_argument(
        "-c", "--comment", default=None, help="Provide a comment for the action"
    )
    parser.add_argument("--noemail", action="store_true", help="Do not send email")


@command(setup=setup_mk_release_args)
def mk_release(dm, args: argparse.Namespace) -> int:
    """Make a SITaR select/integrate/release based on the current workspace"""
    email = None
    if not args.noemail:
        config_dir = Path(os.environ["QC_CONFIG_DIR"])
        fname = config_dir / "project.xml"
        LOGGER.info("Parsing %s to find email to notify...", str(fname))
        email = dm.parse_project_xml(fname)
        LOGGER.info("Using email: %s", email)
# TODO - send email(Already implemented, need to modify with MIME basedd email)
    args.mod_list = dm.flat_release_submit(
        args.mods, args.snap, args.comment, email=email
    )
    if not args.mod_list:
        return 1
    args.version = args.snap
    return 0


def setup_lookup_args(parser):
    """handle the command line arguments for lookup"""
    parser.add_argument(
        "-o",
        "--output",
        help="Specify the output file to use",
        metavar="FILENAME",
        type=str,
        default="",
    )
    # parser.add_argument("-a", "--all", help="Display all submits not just the latest", action="store_true", default=False)


@command(setup=setup_lookup_args)
def lookup(dm, args: argparse.Namespace) -> int:
    """Generate a report of submits that are ready to integrate"""
    # TODO - add in support for the all switch
    mod_list = dm.get_sitr_update_list(args.module)
    if not mod_list:
        LOGGER.info("No new submits to integrate")
    elif args.output:
        write_mod_versions(mod_list, args.output)
    else:
        # TODO - add in support for writing to a file
        dm.display_mod_list(mod_list)
    return 0


def setup_integrate_args(parser):
    """handle the command line arguments for integrate"""
    # TODO - add nopop?
    parser.add_argument(
        "-l", "--local", action="store_true", help="Run locally vs via bsub"
    )
    parser.add_argument(
        "-i",
        "--input",
        metavar="FILENAME",
        help="Specify the file for the module versions to integrate",
        type=str,
        default="",
    )


@command(setup=setup_integrate_args)
def integrate(dm, args: argparse.Namespace) -> int:
    """Run integrate command (must be run as Integrator)"""
    if args.input:
        mod_list = read_mod_versions(args.input)
    else:
        mod_list = dm.get_sitr_update_list(args.module)
    if not mod_list:
        LOGGER.warn("Nothing to integrate")
    else:
        dm.display_mod_list(mod_list)
        if Dsync.prompt_to_continue():
            dm.sitr_integrate(mod_list)
    return 0


def setup_int_release_args(parser):
    """handle the command line arguments for release"""
    parser.add_argument(
        "-c", "--comment", default=None, help="Provide a comment for the action"
    )
    parser.add_argument(
        "-i",
        "--input",
        metavar="FILE",
        type=str,
        default="",
        help="Specify file with module versions to integrate",
    )
    parser.add_argument(
        "-n", "--noemail", action="store_true", help="Do not send email"
    )
    parser.add_argument(
        "-l", "--local", action="store_true", help="Run locally vs via bsub"
    )


@command(setup=setup_int_release_args)
def int_release(dm, args: argparse.Namespace) -> int:
    """Perform a SITaR integrate and release (must be run as Integrator)"""
    if args.input:
        mod_list = read_mod_versions(args.input)
    else:
        mod_list = dm.get_sitr_update_list(args.module)
    if not mod_list:
        LOGGER.warn("Nothing to integrate")
    else:
        dm.display_mod_list(mod_list)
        if Dsync.prompt_to_continue():
            dm.sitr_integrate(mod_list)
    email = None
    if not args.noemail:
        config_dir = Path(os.environ["QC_CONFIG_DIR"])
        fname = config_dir / "project.xml"
        LOGGER.info("Parsing %s to find email to notify...", str(fname))
        email = dm.parse_project_xml(fname)
        LOGGER.info("Using email: %s", email)
# TODO - send email(Already implemented, need to modify with MIME basedd email)
    return dm.sitr_release(args.comment, email=email)


def setup_release_args(parser):
    """handle the command line arguments for release"""
    parser.add_argument(
        "-c", "--comment", default=None, help="Provide a comment for the action"
    )
    parser.add_argument(
        "-n", "--noemail", action="store_true", help="Do not send email"
    )


@command(setup=setup_release_args)
def release(dm, args: argparse.Namespace) -> int:
    """Perform a SITaR release only (must be run as Integrator)"""
    email = None
    if not args.noemail:
        config_dir = Path(os.environ["QC_CONFIG_DIR"])
        fname = config_dir / "project.xml"
        LOGGER.info("Parsing %s to find email to notify...", str(fname))
        email = dm.parse_project_xml(fname)
        LOGGER.info("Using email: %s", email) # TODO - send email(Already implemented, need to modify with MIME basedd email)
    return dm.sitr_release(args.comment, email=email)


def setup_args_parser():
    """Configures the argument parser."""
    parser = argparse.ArgumentParser(
        description="Script to run SITaR commands.",
        add_help=True,
        argument_default=None,  # Global argument default
    )
    parser.add_argument(
        "-d", "--debug", action="store_true", help="enable debug outputs"
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Add in the force switch to populates",
    )
    # parser.add_argument(
    #     "-U",
    #     "--update_snap",
    #     action="store_true",
    #     help="Put the specified module into update mode and populate the latest tag",
    # )
    # parser.add_argument(
    #     "-r",
    #     "--restore",
    #     action="store_true",
    #     help="Restore the specified module to the latest baseline",
    # )
    # parser.add_argument(
    #     "-C", "--checkin", action="store_true", help="Check in the module"
    # )
    # parser.add_argument(
    #     "-P", "--pop_tag", help="Populate the specified tag of the selected module"
    # )
    # parser.add_argument(
    #     "-g", "--tag_sch", help="Tag the schematics/symbols in the module"
    # )
    # parser.add_argument(
    #     "-l",
    #     "--lookup",
    #     action="store_true",
    #     help="Do a lookup for submits not yet integrated",
    # )
    parser.add_argument(
        "-c", "--comment", default=None, help="Provide a comment for the action"
    )
    # parser.add_argument(
    #     "-D", "--directory", help="Specify the directory to the workspace"
    # )
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
    commands = parser.add_subparsers(
        metavar="COMMAND", dest="command", help="one of the supported commands below"
    )
    for key, value in globals().items():
        if callable(value) and getattr(value, "__cmd__", None) is True:
            subparser = add_command_parser(commands, key, value)
            # FIXME: nasty hack
            if key not in (
                "status",
                "repair_ws",
                "jira",
                "gui",
                "populate",
                "integrate",
                "int_release",
                "release",
                "pop_latest",
                "mk_release",
                "setup_ws",
                "request_branch",
                "mk_branch",
                "mk_tapeout_ws",
                "mk_lib",
                "updatehrefs",
            ):
                subparser.add_argument(
                    "module", default=None, help="Module(s) to operate on", nargs="*"
                )
            setup = getattr(value, "__setup__", None)
            if callable(setup):
                setup(subparser)
    args = parser.parse_args()
    if args.command is None and not args.interactive:
        parser.print_help()
        sys.exit(1)
    # FIXME: a really nasty hack for now.
    args.__dict__.update(
        checkin=args.command == "checkin",
        mods=[],
        update=args.command == "update",
        update_snap=args.command == "update_snap",
        pop_modules=args.command == "pop_modules",
        pop_tag=args.command == "pop_tag",
        tag_sch=args.command == "tag_sch",
        show_checkouts=args.command == "show_checkouts",
        submit=args.command == "submit",
        show_locks=args.command == "show_locks",
        show_unmanaged=args.command == "show_unmanaged",
        snapshot=args.command == "snapshot",
        int_release=args.command == "int_release",
        release=args.command == "release",
        mk_release=args.command == "mk_release",
        setup_ws=args.command == "setup_ws",
        request_branch=args.command == "request_branch",
        mk_branch=args.command == "mk_branch",
        restore=args.command == "restore",
        populate=args.command == "populate",
        lookup=args.command == "lookup",
        check_tag=args.command == "check_tag",
        compare=args.command == "compare",
        is_integrate=args.command == "integrate",
        status=args.command == "status",
    )
    if not hasattr(args, "module"):
        # FIXME: nasty hack - needed until refactored all commands
        setattr(args, "module", [])
    return args


def dump_dss_logfile_to_log(dm):
    """Log where Dsync will log commands."""
    resp = dm.shell.run_command("log")
        
    for line in resp.splitlines():
        if "Logfile:" in line:
            LOGGER.debug(line.strip())

def run_dmshell_with_args(args, dm) -> int:
    """Run the interactive shell to start stclc for dsync commands."""
    # run through bsub by default, but only for int_release and integrate, otherwise - locally
    exit_code = 0
    with dm.shell.run_shell():
        args.comment = get_comment(
            args.checkin,
            args.submit,
            args.snapshot,
            args.int_release,
            args.release,
            args.mk_release,
            args.request_branch,
            args.mk_branch,
            args.comment,
        )
        wait_for_shell_with_timeout(dm.shell)

        dump_dss_logfile_to_log(dm)
        run_cdws(dm)

        # TODO - add an option to create a JIRA ticket
        # FIXME: Nasty hack
        setattr(args, "module_given", bool(args.module))
        sitr_mods, modules = get_sitr_modules(
            dm,
            args.module,
            args.update,
            args.update_snap,
            args.pop_modules,
            args.pop_tag,
            args.checkin,
            args.tag_sch,
            args.show_checkouts,
            args.submit,
            args.snapshot,
        )
        args.mods = sitr_mods
        args.module = modules
        if args.interactive:
            import IPython
            IPython.embed()
        elif args.command and callable(args.func):
            LOGGER.debug("RUNNING: %s", args.command)
            exit_code = args.func(dm, args)
            # TODO - need to send the exit command
    return exit_code

def run_intshell_with_args(args, dm) -> int:
    """Run the interactive shell to start stclc in the integrator mode."""
    dm.force_integrate_mode()
    with dm.shell.run_shell():
        wait_for_shell_with_timeout(dm.shell)
        run_cdws(dm)
        if args.mk_release:
            dm.sitr_integrate(args.mod_list, nopop=True)
            dm.sitr_release(args.comment, skip_check=True, on_server=True)
            # TODO - send email
        if args.request_branch:
            sitr_alias = f"baseline_{args.version}"
            # TODO - check for errors
            dm.create_branch(args.version, sitr_alias, args.comment)
            # TODO - add in a JIRA email
        if args.mk_branch:
            sitr_alias = f"baseline_{args.version}"
            dm.force_version(sitr_alias)
            mod_list = dm.branch_modules(
                args.mods, args.mod_list, args.version, args.comment
            )
            if not mod_list:
                dm.sitr_integrate(mod_list, nopop=True)
                dm.sitr_release(args.comment, skip_check=True, on_server=True)
    return 0

def run_cadshell_with_args(args, cad) -> int:
    """Run the interactive shell to start cadence for CIW commands."""
    exit_code = 0
    with cad.shell.run_shell():
        wait_for_shell_with_timeout(cad.shell, "Cadence")
        # TODO - need to get the logfile
        if args.interactive:
            import IPython
            IPython.embed()
        elif args.command and callable(args.func):
            LOGGER.debug("RUNNING: %s", args.command)
            exit_code = args.func(cad, args)
            # TODO - need to send the exit command
    return exit_code

def run_with_args(args) -> int:
    """Run the main script entrypoint with the given args, return the exit code."""
    log.info("Logging to %s", str(LOG_FILE))
    if args.debug:
        log.set_debug()
    run_doctests(args.test)
    start_dir = get_start_dir(None)
    if running_inside_dmsh():
        return 1

    is_release_or_integrate = args.command in ("int_release", "integrate")
    bsub_mode = not getattr(args, "local", False) and is_release_or_integrate
    dm, dm_shell = setup_dmsh(start_dir, args.test, bsub_mode=bsub_mode)

    if not args.command in ("mk_lib", "request_branch"):
        exit_code = run_dmshell_with_args(args, dm)
        if exit_code:
            return exit_code

    if args.command in ("mk_lib"):
        start_dir = os.environ["PROJ_USER_WORK"]
        cad = Cadence.Cadence(cwd=start_dir, test_mode=args.test)
        ciw_shell = Process.Process()
        cad.configure_shell(ciw_shell)
        exit_code = run_cadshell_with_args(args, cad)
        if exit_code:
            return exit_code

    if args.command in ("mk_tapeout_ws"):
        config = sitar.get_config()
        ws = sitar.init_ws_builder( config, args.dev_name, args.ws_name)
        ws.create_shared_ws(args.ws_name)

    # Relaunch the DM shell as the integrator
    if args.command in ("mk_release", "request_branch", "mk_branch"):
        exit_code = run_intshell_with_args(args, dm)
        if exit_code:
            return exit_code
    return 0


def main() -> int:
    """
    Wrapper around main script entrypoint with the arguments passed at run-time,
    Does not return, terminates with the returned the exit code.
    """
    args = setup_args_parser()
    exit_code = run_with_args(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
