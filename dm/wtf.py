#! /pkg/qct/software/python/3.6.0/bin/python
"""
Supports running SITaR commands via a DM shell.
"""
import argparse
import os
import sys
from functools import wraps
from pathlib import Path

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
        sys.path.insert(0, pwd + "/../log")
        import log
    except ImportError:
        pass


import dm

# from dm import *  # isort:skip
try:
    from dm import *
except ImportError:
    try:
        pwd = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, pwd + "/../dm")
        from dm import *
    except ImportError:
        pass
# from dm import *  # isort:skip

LOGGER = log.getLogger(__name__)


def command(*, setup: callable = None):
    """
    Decorator for functions implementing commands inside of the virtualenv.
    """

    def inner(func):
        @wraps(func)
        def wrapped(dssc, args: argparse.Namespace):
            return func(dssc, args)

        # Add command and setup attributes to command functions
        # to help set up each command parser in setup_args_parser function
        # using globals() dict
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


def setup_dmsh(start_dir, test_mode, bsub_mode=False):
    """
    Sets up DMSH and prepares to run it, returning the configured dssc and
    dm_shell."""
    LOGGER.debug(f"start dir = {start_dir}")
    dssc = dm.Wtf_dm(cwd=start_dir, test_mode=test_mode, bsub_mode=bsub_mode)
    env_dir = Path(os.environ["SYNC_DEVAREA_DIR"])
    # TODO - this will not work in shared
    root_dir = dm.find_sitr_root_dir(start_dir)
    # TODO - what about a shared ws?
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
    dssc.workspace_type = "Design"
    if role == "Shared":
        if env_dir.stem.startswith("tapeout"):
            dssc.workspace_type = "Tapeout"
            dssc.tapeout_tag = env_dir.stem
        elif env_dir.stem.startswith("shared"):
            dssc.workspace_type = "Shared"
    elif role == "Integrate":
        dssc.workspace_type = role
    dm_shell = dm.Process()
    dssc.configure_shell(dm_shell)
    return dssc, dm_shell


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


def get_sitr_modules(
    dssc,
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
    only_update = False
    if not (is_update or is_update_snap) and (
        is_pop_modules
        or is_pop_tag
        or is_checkin
        or is_tag_sch
        or is_show_checkouts
        or is_submit
        or is_snapshot
    ):
        only_update = True

    dssc.wtf_get_sitr_modules(given_mods, only_update)


def setup_populate_args(parser):
    """handle the command line arguments for pop_modules"""
    parser.add_argument("-f,--force", action="store_true", help="Force populate")


@command(setup=setup_populate_args)
def populate(dssc, args: argparse.Namespace) -> int:
    """Populate a SITaR workspace"""
    return dssc.populate(args.force)


@command(setup=setup_populate_args)
def pop_modules(dssc, args: argparse.Namespace) -> int:
    """Populate all modules in update mode in the SITaR workspace"""
    return dssc.pop_modules(args.force)


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
def populate_tag(dssc, args: argparse.Namespace) -> int:
    """Populate a tag in a SITaR workspace when modules are in update mode"""
    return dssc.populate_tag(args.tag, args.force)


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
def pop_latest(dssc, args: argparse.Namespace) -> int:
    """Populate a SITaR workspace for the flat release flow"""
    return dssc.pop_latest(args.tag, args.force)


@command()
def status(dssc, args: argparse.Namespace) -> int:
    """Perform a SITaR status"""
    return dssc.status()


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
def update(dssc, args: argparse.Namespace) -> int:
    """Set module(s) (or all modules) in update mode"""
    # TODO - do we need the force switch? Or no overwrite?
    return dssc.update(args.config, args.delta)


@command()
def restore(dssc, args: argparse.Namespace) -> int:
    """Restore the specified module to the latest baseline"""
    return dssc.restore()


@command()
def show_checkouts(dssc, args: argparse.Namespace) -> int:
    """Scan for checkouts in the module"""
    return dssc.show_checkouts()


@command()
def show_locks(dssc, args: argparse.Namespace) -> int:
    """Show the files locked in the module module"""
    return dssc.show_locks()


@command()
def show_unmanaged(dssc, args: argparse.Namespace) -> int:
    """Show unmanaged files in the specified modules"""
    return dssc.show_unmanaged()


@command()
def showstatus(dssc, args: argparse.Namespace) -> int:
    """Runs showstatus command for the modules"""
    # When no explicit modules are given, pass none.
    return dssc.showstatus()


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
def showhrefs(dssc, args: argparse.Namespace) -> int:
    """Show the Hrefs for the specified modules"""
    return dssc.showhrefs(args.submod, args.output)


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
def updatehrefs(dssc, args: argparse.Namespace) -> int:
    """Update Hrefs from a XLS file, optionally filtering by submodule"""
    return dssc.updatehrefs(args.submod, args.input)


def setup_check_tag_args(parser):
    """handle the command line arguments for check tag"""
    parser.add_argument(
        "-n", "--tag", help="Specify the tagname", metavar="TAG", type=str
    )


@command(setup=setup_check_tag_args)
def check_tag(dssc, args: argparse.Namespace) -> int:
    """Checks for the TAG for files in MODULE"""
    return dssc.check_tag(args.tag)


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
def compare(dssc, args: argparse.Namespace) -> int:
    """Run a compare on the specified MODULES vs Trunk/Version/Tag"""
    return dssc.compare(args.mods, args.module, args.tag, args.trunk, args.baseline)


@command()
def vhistory(dssc, args: argparse.Namespace) -> int:
    """This command will display the version history for the module"""
    # FIXME: Check which Dsync output parser helpers should be used
    return dssc.vhistory(args.module)


@command(setup=setup_check_tag_args)
def overlay_tag(dssc, args: argparse.Namespace) -> int:
    """Overlay the specified tag in the specified modules and check-in"""
    return dssc.overlay_tag(args.mods, args.module, args.tag)


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
def setup_ws(dssc, args: argparse.Namespace) -> int:
    """Setup a workspace after it has been created"""
    # TODO - send email
    return dssc.setup_ws()


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
def submit(dssc, args: argparse.Namespace) -> int:
    """Perform a SITaR submit / snapshot submit"""
    return dssc.submit(args.snap, args.pop, args.comment, args.noemail)


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
def mk_tapeout_ws(dssc, args: argparse.Namespace) -> int:
    """Make the tapeout workspace for the project"""
    return dssc.mk_tapeout_ws(args.tag)


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
    parser.add_argument("--noemail", action="store_true", help="Do not send email")


@command(setup=setup_request_branch_args)
def request_branch(dssc, args: argparse.Namespace) -> int:
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
        help="Specify the flat tagname for the branch",
        metavar="TAG",
        type=str,
        default="",
    )
    parser.add_argument(
        "-t",
        "--tapeout",
        help="Specify the tapeout tag for the branch",
        metavar="TAPEOUT",
        type=str,
        default="",
    )
    parser.add_argument(
        "-c", "--comment", default=None, help="Provide a comment for the action"
    )


@command(setup=setup_mk_branch_args)
def mk_branch(dssc, args: argparse.Namespace) -> int:
    """Make a branch in the current workspace where the tapeout tag is populated"""
    return dssc.mk_branch(args.version, args.comment, args.tag, args.tapeout)


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
def mk_release(dssc, args: argparse.Namespace) -> int:
    """Make a SITaR select/integrate/release based on the current workspace"""
    return dssc.mk_release(args.snap, args.comment, args.noemail)


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
def lookup(dssc, args: argparse.Namespace) -> int:
    """Generate a report of submits that are ready to integrate"""
    # TODO - add in support for the all switch
    return dssc.lookup(args.output)


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
def integrate(dssc, args: argparse.Namespace) -> int:
    """Run integrate command (must be run as Integrator)"""
    return dssc.integrate(args.input)


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
def int_release(dssc, args: argparse.Namespace) -> int:
    """Perform a SITaR integrate and release (must be run as Integrator)"""
    return dssc.int_release(args.comment, args.input, args.noemail)


def setup_release_args(parser):
    """handle the command line arguments for release"""
    parser.add_argument(
        "-c", "--comment", default=None, help="Provide a comment for the action"
    )
    parser.add_argument(
        "-n", "--noemail", action="store_true", help="Do not send email"
    )


@command(setup=setup_release_args)
def release(dssc, args: argparse.Namespace) -> int:
    """Perform a SITaR release only (must be run as Integrator)"""
    return dssc.release(args.comment, args.noemail)


def choose_log_file() -> str:
    """
    Utility function for jira command to display log files options
    and let user choose a log file
    """
    # Choose log file from list
    # return list of pairs (command, log_file_Path)
    log_files_classfied = log.classify_logs_command(LOG_DIR)

    if not log_files_classfied:
        LOGGER.info("Could not find log files.")
        sys.exit(1)

    for index, pair in enumerate(log_files_classfied, 1):
        command, log_file_path = pair
        option = f"{index} : {command} : '{log_file_path}' "
        print(option)
    # User choose log file
    option_index = None
    while option_index not in range(1, len(log_files_classfied) + 1):
        try:
            option_index = int(input("Enter option number: "))
        except ValueError:
            print("Please enter an integer in options.")

    log_file = log_files_classfied[option_index - 1][1]

    return log_file


def ask_string_input(prompt: str) -> str:
    """
    Utility function for jira to get string input
    """
    # TODO input validation ?
    while True:
        string = input(prompt)
        if string:
            break
    return string


# args argument is kept so not to break decorator signature
@command()
def jira(dssc, args: argparse.Namespace) -> int:
    """
    Send jira email with subject and comment and an attachment log_file
    """
    subject = ""
    comment = ""
    JIRA_EMAILS = ["email1@jira_example.com", "email2@jira_example.com"]

    log_file = choose_log_file()

    subject = ask_string_input("Please enter subject: ")
    comment = ask_string_input("Please enter Comment: ")

    # Ask user for email to send jira
    for index, email in enumerate(JIRA_EMAILS, 1):
        option = f"{index} : {email}"
        print(option)

    option_index = None
    while option_index not in range(1, len(JIRA_EMAILS) + 1):
        try:
            option_index = int(input("Enter option number: "))
        except ValueError:
            print("Please enter an integer in options.")

    email = JIRA_EMAILS[option_index - 1]

    LOGGER.debug(
        f"JIRA Email sent with subject={subject}, comment={comment}, email={email}, logfile={log_file}"
    )
    return dssc.jira(
        subject=subject, comment=comment, log_file=Path(log_file), email=email
    )


#  "Number : user_command: log_file_name"
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
        jira=args.command == "jira",
    )
    if not hasattr(args, "module"):
        # FIXME: nasty hack - needed until refactored all commands
        setattr(args, "module", [])
    return args


def run_dmshell_with_args(args, dssc) -> int:
    """Run the interactive shell to start stclc for dsync commands."""
    # run through bsub by default, but only for int_release and integrate, otherwise - locally
    exit_code = 0
    with dssc.shell.run_shell():
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
        wait_for_shell_with_timeout(dssc.shell)

        dssc.initial_setup()
        get_sitr_modules(
            dssc,
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

        # TODO - add an option to create a JIRA ticket
        if args.interactive:
            import IPython

            IPython.embed()
        elif args.command and callable(args.func):
            LOGGER.debug("RUNNING: %s", args.command)
            exit_code = args.func(dssc, args)
            # TODO - need to send the exit command
    return exit_code


def run_intshell_with_args(args, dssc) -> int:
    """Run the interactive shell to start stclc in the integrator mode."""
    dssc.force_integrate_mode()
    if args.mk_branch:
        dssc.wtf_set_dev_dir()
    with dssc.shell.run_shell():
        wait_for_shell_with_timeout(dssc.shell)
        dssc.initial_setup()
        if args.mk_release:
            dssc.mk_release_int(args.comment)
            # TODO - send email
        if args.request_branch:
            email = None
            if not args.noemail:
                email = "mgajjar"  # This will generate a JIRA ticket
                LOGGER.info("Using email: %s", email)
            dssc.request_branch(args.version, args.comment, email)
        if args.mk_branch:
            dssc.mk_branch_int(args.version, args.comment)
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
    dssc, dm_shell = setup_dmsh(start_dir, args.test, bsub_mode=bsub_mode)

    # No need to run any shell, just send JIRA email.
    if args.command in ("jira"):
        exit_code = args.func(dssc, args)
        return exit_code

    if not args.command in ("mk_lib", "request_branch"):
        exit_code = run_dmshell_with_args(args, dssc)
        if exit_code:
            return exit_code

    if args.command in ("mk_lib"):
        start_dir = os.environ["PROJ_USER_WORK"]
        cad = Cadence.Cadence(cwd=start_dir, test_mode=args.test)
        ciw_shell = dm.Process()
        cad.configure_shell(ciw_shell)
        exit_code = run_cadshell_with_args(args, cad)
        if exit_code:
            return exit_code

    if args.command in ("mk_tapeout_ws"):
        config = sitar.get_config()
        ws = sitar.init_ws_builder(config, args.dev_name, args.ws_name)
        ws.create_shared_ws(args.ws_name)

    # Relaunch the DM shell as the integrator
    if args.command in ("mk_release", "request_branch", "mk_branch"):
        exit_code = run_intshell_with_args(args, dssc)
        if exit_code:
            return exit_code
    return 0


def main() -> int:
    """
    Wrapper around main script entrypoint with the arguments passed at run-time,
    Does not return, terminates with the returned the exit code.
    """
    args = setup_args_parser()
    used_arguments = " ".join(sys.argv[1:])

    # Log used command + arguments to filer log files based on it
    LOGGER.debug(f"######### [command]={used_arguments} #########")

    exit_code = run_with_args(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
