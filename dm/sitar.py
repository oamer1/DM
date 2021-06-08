#! /pkg/qct/software/python/3.6.0/bin/python
import argparse
import csv
import getpass
import logging
import logging.handlers
import os
import re
import shutil
import subprocess
import sys
from collections import OrderedDict
from configparser import ConfigParser
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Dict, List, Iterable, Optional
from .utils import ask_option_number, ask_string_input, choose_option
import tabulate

SCRIPT_NAME = Path(__file__).name
SCRIPT_DIR = Path(__file__).parent

HOME_LOG_FILE = Path.home() / ".cache"

LOCAL_CACHE_FILE = f"~/.cache/{SCRIPT_NAME}_cache.cfg"
ISOFORMAT = "%Y-%m-%dT%H:%M:%S"


Row = Dict[str, str]  # Resule of parsing sda output rows
Details = Dict[str, str]  # Used for parsed (cached) area/development data

logger = logging.getLogger(__name__)


def log_debug(msg: str):
    logger.debug(msg)
    print(f"DEBUG: {msg}")


def log_info(msg: str):
    logger.info(msg)
    print(f"INFO: {msg}")


def log_warn(msg: str):
    logger.warning(msg)
    print(f"WARN: {msg}")


def log_error(msg: str, exc_info: bool = False):
    logger.error(msg, exc_info=exc_info)
    print(f"ERROR: {msg}")
    sys.exit(1)


# TODO - should this be a class?
class WS_Builder(object):
    """Class for creating a SITaR based workspace
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

    def get_dir_name(self, name: str = None) -> str:
        """get the dirname for the sitr workspace"""
        user_name = getpass.getuser()
        if name:
            dir_name = name
        elif self.role == "Integrate":
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

    def setup_sitr_workdir(self, name: str, shared_name: str = "") -> bool:
        """setup the attributes for the workspace"""
        user = getpass.getuser()
        if shared_name:
            self.work_dir = self.project_dir / shared_name
            self.user_dir = self.work_dir / name
            self.ws_name = f"{self.development_name}_{shared_name}"
        else:
            self.work_dir = self.project_dir / name
            self.user_dir = self.work_dir
            self.ws_name = f"{self.development_name}_{name}"

        self.dsgn_proj = self.work_dir / self.container_name
        self.proj_env = {
            "SYNC_DEVAREA_DIR": self.work_dir,
            "QC_SYNC_DEVNAME": self.development_name,
            "PROJECT_DIR": self.project_dir,
            "DSGN_PROJ": self.dsgn_proj,
            "LD_LIBRARY_PATH": "/pkg/qct/software/tcl/8.4.6/lib",
            "QC_CONFIG_DIR": "${DSGN_PROJ}/config",
        }
        return self.work_dir.exists()

    def setup_sitr_env(
        self, chip_name: str, chip_version: str, base_path: "Path"
    ) -> None:
        """setup the environment variables for creating the workspace using sda"""
        project_name = chip_name + "_" + chip_version
        development_dir = base_path / project_name.lower()
        config_name = "Analog"
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
            log_info(f"Running subprocess {arg_list}")
        else:
            child = subprocess.Popen(arg_list, env=sub_env)
            exit_code = child.wait()
            # Throw Exception
            if exit_code:
                raise Exception(
                    f"Error encountered when creating workspace {exit_code}"
                )

    def setup_shared_ws(self) -> None:
        """setup the workspace (which is in a different location than the work dir"""
        if self.test_mode:
            log_info(f"Making the directory {self.user_dir}")
        else:
            self.user_dir.mkdir(exist_ok=True)

        user_dsgn_proj = self.user_dir / self.container_name

        if self.test_mode:
            log_info(f"Adding symlink to {self.dsgn_proj}")
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
            log_info(f"Creating {setup_file} = {proj_setup}")
        else:
            setup_file.write_text(proj_setup)

        setup_file = self.user_dir / ".shrc.project"
        if self.test_mode:
            log_info(f"Creating {setup_file} = {sh_setup}")
        else:
            setup_file.write_text(sh_setup)

    def setup_cds_lib(self) -> None:
        """setup the cds.lib file for launching cadence"""
        cds_file = self.user_dir / "cds.lib"
        cds_file_contents = (
            "SOFTINCLUDE "
            "$TECH_DIR/$FOUNDRY/$PROCESS/$TECH_VERSION/qcCadence/inits/cds.lib\n"
        )
        cds_file_contents += f"SOFTINCLUDE ./{self.container_name}/cds.lib.project\n"
        if self.test_mode:
            log_info(f"Creating {cds_file} = {cds_file_contents}")
        else:
            cds_file.write_text(cds_file_contents)

    def copy_ws_setup_files(self) -> None:
        """
        copy over files for cadence from the config module
        """
        for file in [
            "cdsLibMgrProject.il",
            "hdl.var",
            "hed.env",
            "hierEditor.env",
            # "run_ams",
        ]:
            src = self.dsgn_proj / "config" / file
            if src.exists() and not self.test_mode:
                if self.test_mode:
                    log_info(f"Copying {src}")
                else:
                    shutil.copy2(src, self.user_dir)
            else:
                log_warn(f"Cannot access {src}")

    def setup_ws(self) -> None:
        """call the different methods to setup a workspace after sda has been called"""
        self.setup_source_files()
        self.setup_cds_lib()
        self.copy_ws_setup_files()

    def create_shared_ws(self, dir_name: str) -> bool:
        """create the shared workspace"""
        if self.setup_sitr_workdir(getpass.getuser(), dir_name):
            log_info(f"The workspace {self.ws_name} already exists in {self.work_dir}")
            return False
        log_info(f"Creating the shared workspace {self.ws_name} in {self.work_dir}")
        arg_list = [
            "sda",
            "mk",
            self.ws_name,
            self.development_name,
            "-assignment",
            self.role,
            "-shared",
            "-path",
            self.work_dir,
        ]

        try:

            self.run_sda(arg_list)
            self.setup_shared_ws()
            self.setup_ws()

        except Exception as err:
            log_error(f"Error creating shared ws {err}", exc_info=True)

        return True

    def join_shared_ws(self, dir_name: str) -> bool:
        """call sda so that the user joins the shared workspace"""
        if not self.setup_sitr_workdir(getpass.getuser(), dir_name):
            log_info(f"The workspace {self.ws_name} does not exist in {self.work_dir}")
            return False
        log_info(f"Joining the shared workspace {self.ws_name} in {self.work_dir}")
        arg_list = ["sda", "join", self.ws_name, "-development", self.development_name]
        self.run_sda(arg_list)
        self.setup_shared_ws()
        self.setup_ws()
        return True

    def create_ws(self, dir_name: str) -> bool:
        """create an individual workspace"""
        if self.setup_sitr_workdir(dir_name):
            log_info(f"The workspace {self.ws_name} already exists in {self.work_dir}")
            return False
        log_info(f"Populating the workspace {self.ws_name} in {self.work_dir}")
        arg_list = [
            "sda",
            "mk",
            self.ws_name,
            self.development_name,
            "-assignment",
            self.role,
            "-path",
            self.work_dir,
        ]

        try:

            self.run_sda(arg_list)
            self.setup_ws()

        except Exception as err:
            log_error(f"Error creating ws {err}", exc_info=True)

        return True

    @classmethod
    def setup_base_args(cls, parser: argparse.ArgumentParser):
        parser.add_argument(
            "dev_name",
            help="Specify the name of the development",
            type=str,
            metavar="dev_name",
            default="",
            nargs="?",
        )
        parser.add_argument(
            "-n",
            "--name",
            help="Specify the workspace name",
            type=str,
            default="",
            dest="ws_name",
        )

    @classmethod
    def setup_common_args(cls, parser: argparse.ArgumentParser):
        cls.setup_base_args(parser)
        parser.add_argument(
            "-i",
            "--integrator",
            action="store_true",
            help="create an integrator workspace",
        )

    @classmethod
    def setup_make_join_args(cls, parser: argparse.ArgumentParser):
        cls.setup_common_args(parser)
        parser.add_argument(
            "-s",
            "--shared",
            action="store_true",
            help="Make/join a shared workspace",
            default=False,
        )
        parser.add_argument(
            "-t",
            "--tapeout",
            action="store_true",
            help="Make/join a tapeout workspace",
            default=False,
        )
        parser.add_argument(
            "-r",
            "--regression",
            action="store_true",
            help="Make/join a regression workspace",
            default=False,
        )
        parser.add_argument(
            "-p",
            "--release",
            action="store_true",
            help="Make/join a release workspace",
            default=False,
        )

    def validate_make_join_args(self, args: argparse.Namespace) -> None:
        """Validate make_ws / join_ws args."""
        if args.command not in ("make_ws", "join_ws"):
            log_error(f"Unknown command {args.command}")

        flags = sum(
            1
            for f in (
                args.shared,
                args.tapeout,
                args.regression,
                args.release,
                args.integrator,
            )
            if f
        )
        if flags > 1:  # make_ws / join_ws takes one of none of these
            log_error(
                "Only one of --integrator, --shared, --tapeout, --regression, or --release must be specified."
            )

        # Set default name based on flags, if not given:
        if args.shared:
            if not args.ws_name:
                setattr(args, "ws_name", "shared")
            elif not args.ws_name.startswith("shared"):
                log_error("The layout shared workspace name must start with shared")

        elif args.release:
            if not args.ws_name:
                setattr(args, "ws_name", "release_prep")
            elif not args.ws_name.startswith("release_prep"):
                log_error(
                    "The release prep workspace name must start with release_prep"
                )

        elif args.regression:
            if not args.ws_name:
                setattr(args, "ws_name", "regression")
            elif not args.ws_name.startswith("regression"):
                log_error("The regression workspace name must start with regression")

        elif args.tapeout:
            if not args.ws_name:
                setattr(args, "ws_name", f"tapeout_{self.development_name.lower()}")
            elif not args.ws_name.startswith("tapeout_"):
                log_error("The tapeout workspace name must start with tapeout")

        elif not args.ws_name:
            setattr(args, "ws_name", self.get_dir_name())


class TableParser:
    """
    Parses text-based table output of the `sda` commands with a format like:
    Header One    Another Header     Third
    ----------    --------------     -----
    Value1        Second Value       3rd
    Value 2       2nd Value
    ...
    See the example dumps in "data/dump*".
    NOTE: The following assumptions are made for the output:
    * columns are delimited by variable whitespace;
    * both headers and values can contain whitespace;
    * leading and trailing whitespace from headers and values is stripped;
    * headers can be separated from the values with uniform underlining;
    * headers line must be present (anything before is ignored);
    * some values can be empty;
    * there is a single table with fixed number of columns;
    * results are Row entires with shorter keys.
    """

    COMMAND = []  # command to run in order to get the output.
    TIMEOUT = 300.0  # time in seconds to wait for the command to return output.
    DELIMITER = "  "  # minimal fixed delimiter between columns.
    SEPARATOR = "-"  # if not empty, used to find the separator after headers.
    KEYS_HEADERS = dict()  # Row keys to header labels mapping.
    DISPLAY_COLUMNS = dict()  # short keys to column labels for display.

    @classmethod
    def run(cls) -> Iterable[str]:
        """
        Runs the COMMAND, capturing and parsing the output, and returning the parsed
        rows (if any).
        """
        start_datetime = datetime.utcnow()
        try:
            cmd = " ".join(cls.COMMAND)
            if not cmd:
                yield from []

            log_debug("Running %r with timeout %.1f ... " % (cmd, cls.TIMEOUT))

            result = subprocess.run(
                cmd,
                timeout=cls.TIMEOUT,
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                shell=True,
            )

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as err:
            log_error("ERROR: %r" % err, exc_info=True)

        else:
            end_datetime = datetime.utcnow()
            secs = (end_datetime - start_datetime).total_seconds()
            log_debug("Command took %.4f seconds" % secs)
            yield from cls._from_lines(result.stdout.decode("utf-8").splitlines())
            # result_lines = result.stdout.decode("utf-8").splitlines()
            #
            # end_datetime = datetime.utcnow()
            # secs = (end_datetime - start_datetime).total_seconds()
            # log_debug("Command took %.4f seconds" % secs)
            # yield from cls._from_lines(result_lines)

    @classmethod
    def _from_lines(cls, lines: Iterable[str]) -> Iterable[Row]:
        """
        Given a file-like source of raw text lines with fixed fields, delimited by
        DELIMITER, yields Rows with the same fields and values from each line.
        Field names are taken from the keys in KEYS_HEADERS, while the values
        should be the header labels that denote the beginning of the table. If
        after the headers follows a separator (e.g. underlining the headers),
        and SEPARATOR is non empty, that line is skipped as well.
        Anything before the headers / separators is ignored.
        """

        headers = tuple(cls.KEYS_HEADERS.values())
        separators = (
            tuple(cls.SEPARATOR * len(header) for header in headers)
            if cls.SEPARATOR
            else ()
        )
        num_fields = len(cls.KEYS_HEADERS)

        reader = csv.DictReader(
            cls._normalized_lines(lines),
            delimiter="\t",
            fieldnames=tuple(cls.KEYS_HEADERS.keys()),
            restkey=None,
        )

        found_headers = False
        found_first_row = False

        for row in reader:
            if found_first_row and len(row) == num_fields:
                yield cls._post_process_row(row)
                continue

            values = tuple(row.values())
            found_headers = found_headers or values == headers
            found_first_row = found_headers and separators and values == separators

    @classmethod
    def _post_process_row(cls, row: Row) -> Row:
        """
        Called on each Row after successfully parsing that row.
        Can be used to further adjust the values format.
        """
        return row

    @classmethod
    def _normalized_lines(cls, lines: Iterable[str]) -> Iterable[str]:
        """
        Attempts to normalize the `lines` as much as possible to make parsing as
        close to parsing tab-delimited values as possible: strips leading/
        trailing whiictespace, splits by DELIMITER, removes empty strings, and
        rejoins the result with tab ("\t").
        """
        for line in lines:
            yield "\t".join(filter(None, map(str.strip, line.split(cls.DELIMITER))))

    @classmethod
    def tabulate(cls, lines: Iterable[Row], format=None) -> None:
        """
        Display a table with the labels in DISPLAY_COLUMNS
        (values), for each row with the matching keys in there.
        """
        table = OrderedDict((header, []) for header in cls.DISPLAY_COLUMNS.values())

        for row in lines:
            for key, value in row.items():
                label = cls.DISPLAY_COLUMNS.get(key, None)
                if label is not None:
                    table[label] += [value]

        print(tabulate.tabulate(table, headers="keys", tablefmt=format or "simple"))


class AreaParser(TableParser):
    """
    Parses the development areas table from the output of `sda ls -area ...`.
    """

    COMMAND = ["sda", "ls", "-area", "-report", "verbose"]
    KEYS_HEADERS = dict(
        # name="Development Area", # added name as first in the order, but in sda ls its second
        development="Development",
        # if the sequence is matching with the output of COMMAND, it stores the right value into .cfg file
        name="Development Area",
        assignment="Assignment",
        shared="Shared",
        external="External",
        orphaned="Orphaned",
        path="Development Area Path",
        development_path="Development Path",
        status="Development Status",
    )

    DISPLAY_COLUMNS = dict(name="Name", development="Development", path="Path")


class DevelopmentParser(TableParser):
    """
    Parses the developments table from the output of `sda ls -development ...`.
    """

    COMMAND = ["sda", "ls", "-development", "-report", "verbose"]
    KEYS_HEADERS = dict(
        name="Development",
        assignments="Assignments",
        data_url="Data URL",
        # name="Development",
        selector="Selector",
        path="Development Path",
        server_url="Server URL",
        status="Status",
    )

    DISPLAY_COLUMNS = dict(
        name="Name", data_url="Data URL", selector="Selector", path="Path"
    )

    @classmethod
    def _post_process_row(cls, row: Row) -> Row:
        """
        Called on each Row after successfully parsing that row.
        Ensure there are no spaces in the values where needed.
        """
        row.update(
            assignments=row["assignments"].replace(" ", ""),
            path=row["path"].replace(" ", ""),
        )
        return row


def save_lines(
    parser: ConfigParser, lines: Iterable[Row], parser_cls: TableParser
) -> None:
    if not parser.has_section("main"):
        parser.add_section("main")

    names = set()
    kind = parser_cls.__name__.replace("Parser", "").lower()
    names_section = f"{kind}s"

    print("------", parser_cls.__name__)

    for row in lines:
        name = row["name"].lower()
        if name in names:
            continue
        # for key_row, key_header in zip(row, parser_cls.KEYS_HEADERS.keys()):
        #     print("##################", key_row, key_header, "##################")
        #     if key_row != key_header:
        #         raise KeyError(f"The headers do not match: {key_row}, {key_header}")

        names.add(name)
        section = f"{kind}:{name}"

        if not parser.has_section(section):
            parser.add_section(section)

        for key, value in row.items():
            parser[section][key] = value

    last_update = datetime.utcnow()
    parser["main"][names_section] = ",".join(sorted(map(str.lower, names)))
    parser["main"]["last_update"] = last_update.isoformat(timespec="seconds")


def command(*, help: str, setup: callable = None):
    def inner(func):
        @wraps(func)
        def wrapped(args: argparse.Namespace, config: ConfigParser):
            return func(args, config)

        wrapped.__cmd__ = True
        wrapped.__setup__ = setup
        wrapped.__help__ = help
        return wrapped

    return inner


def update_cache(config: ConfigParser, cfg: Path, force=False):
    """
    If the local cache does not exist yet, create it (also when force is True),
    otherwise read it.
    """
    if not cfg.exists() or force:
        for parser_cls in (AreaParser, DevelopmentParser):
            lines = parser_cls.run()
            save_lines(config, lines, parser_cls)

        # flag_delete_config = False
        with cfg.open("wt", encoding="utf-8") as c:
            # print(config["main"]["areas"].split(","))
            areas = config["main"]["areas"].split(",")
            development = config["main"]["developments"].split(",")
            if len(areas) == 1 and areas[0] == "":
                log_info("No ws areas saved, ls_ws,set_ws,join_ws will not work")
                config.write(c)
                log_info("Local cache %r updated" % str(cfg))
                # flag_delete_config = True
            elif len(development) == 1 and development[0] == "":
                log_info(
                    "No developements saved, ls_prj, make_ws, join_ws with shared will not work"
                )
                config.write(c)
                log_info("Local cache %r updated" % str(cfg))
                # flag_delete_config = True
            else:
                config.write(c)
                log_info("Local cache %r updated" % str(cfg))

        # if flag_delete_config:
        #     cfg.unlink()
        #     raise Exception("No areas. Not saving the config.")

    else:
        config.read([cfg])


def get_config(skip_update=False) -> ConfigParser:
    """
    If the local cache does not exist yet, create it (also when force is True),
    otherwise read it.
    """
    cfg = Path(LOCAL_CACHE_FILE).expanduser()
    config = ConfigParser(dict_type=OrderedDict)

    if not skip_update:
        # Create the cache initially if missing, but don't do it
        # if the command is refresh, since it will do it anyway.
        update_cache(config, cfg)
    return config


def all_areas(config: ConfigParser) -> Iterable[Row]:
    for name in config["main"]["areas"].split(","):
        section = f"area:{name}"
        area = config[section]
        yield area


@command(help="list workspaces")
def ls_ws(args: argparse.Namespace, config: ConfigParser) -> int:
    """list existing workspaces"""

    AreaParser.tabulate(all_areas(config))
    return 0


def setup_ls_prj_args(parser: argparse.ArgumentParser):
    parser.add_argument(
        "-a",
        "--all",
        help="Show all projects",
        dest="all",
        action="store_true",
    )


@command(help="list projects", setup=setup_ls_prj_args)
def ls_prj(args: argparse.Namespace, config: ConfigParser) -> int:
    """list existing projects"""

    def all_devs() -> Iterable[Row]:
        for name in config["main"]["developments"].split(","):
            section = f"development:{name}"
            dev = config[section]
            yield dev

    all_devs_iter = all_devs()
    # User does not have access to all projects, exclude projects
    # with path <NotAvailable> if arg all not passed
    if not args.all:
        all_devs_iter = filter(
            lambda dev: dev["path"] != "<NotAvailable>", all_devs_iter
        )

    DevelopmentParser.tabulate(all_devs_iter)
    return 0


def get_ws_details(config: ConfigParser, ws_name: str) -> Details:
    """
    Returns the Details for a cached development (workspace)
    by (case insensitive) name.
    Logs an error and exits on error.
    """

    dev_name = ws_name.lower()
    devs = set(config["main"]["developments"].split(","))
    if dev_name not in devs:
        log_error("Unknown development %r!" % dev_name)

    section = f"development:{dev_name}"
    dev = config[section]

    return dev


def init_ws_builder(
    config: ConfigParser,
    dev_name: str,
    integrator: bool = False,
    shared: bool = False,
    require_config: bool = True,
) -> WS_Builder:
    """
    Looks up the given workspace by name in the cached
    config and initializes a WS_Builder instance.
    """

    dev_name = dev_name.lower()
    dev = get_ws_details(config, dev_name)
    ws = WS_Builder()

    if "_v" in dev_name:
        chip_name, _, chip_version = dev["name"].rpartition("_")

    else:
        log_error("Cannot determine chip name and version from %r!" % dev_name)

    base_path = Path(dev["path"]).parent
    ws.setup_sitr_env(chip_name, chip_version, base_path)

    role = None
    if shared:
        role = "Shared"
    elif integrator:
        role = "Integrate"
    else:
        role = "Design"
    ws.setup_sitr_role(role)

    if not ws.config_root.exists() and require_config:
        log_error(f"Cannot access the config root directory ({ws.config_root})")

    return ws


def post_ws_builder(
    config: ConfigParser,
    args: argparse.Namespace,
    ws: WS_Builder,
    ws_state: str = "",
    work_dir_must_exist=True,
):
    """
    Once the WS_Builder does its job, force a cache refresh, and
    output working directory status.
    """

    if work_dir_must_exist and not ws.user_dir.exists():
        log_error(f"The directory {ws.user_dir} was not created.")

    log_info(f"The workspace {ws.user_dir} {ws_state}")

    cfg = Path(LOCAL_CACHE_FILE).expanduser()
    update_cache(config, cfg, force=True)


def find_file(filename: str, cwd: Path = None) -> Optional[Path]:
    """
    Search for the closest filename file in cwd and its parents.
    Returns the full path to filename if found, None otherwise.
    """
    user = getpass.getuser()
    cwd = cwd or Path.cwd()
    current = cwd

    try:
        while True:
            # try:
            #   full_path = current/ user / filename
            # except:
            #     print('Cant Find')
            # else:
            #   full_path = current / filename
            full_path = current / filename
            log_debug("Looking for %s..." % full_path)

            if str(current) == str(cwd.root):
                raise ValueError

            if full_path.exists():
                log_debug("Found at %s" % full_path.parent)
                return full_path

            current = current.parent

    except ValueError:
        log_warn("%s NOT found anywhere in %s or its parents" % (filename, cwd))

    return None


def get_sitr_root_dir(filename=".cshrc.project", cwd: Path = None) -> Optional[Path]:
    """Try to find the root SITaR workspace directory"""

    path = find_file(filename, cwd)
    if path:
        return path.parent

    log_warn("Cannot find %s!" % filename)
    return None


def parse_rc_project(filename: Path, ws_var: str = "SYNC_DEVAREA_DIR") -> str:
    """
    Parses the given .shrc.project or .cshrc.project file
    to extract the given variable and return its value.
    """
    if not filename.exists():
        log_error("%s does NOT exist!" % filename)

    with filename.open("rt", encoding="utf-8") as f:
        for line in f:
            if ws_var not in line:
                continue

            line = line.strip()
            prefix, _, suffix = line.partition("=")
            ws_name = Path(suffix).name

    return ws_name


@command(help="create workspace", setup=WS_Builder.setup_make_join_args)
def make_ws(args: argparse.Namespace, config: ConfigParser) -> int:
    """
    Create a SITaR workspace for the current project.
    """
    # Show available project names and let user choose
    dev_projects = config["main"]["developments"].split(",")
    # if dev_name not provided ask
    if not args.dev_name:
        dev_name = choose_option(dev_projects)
        args.dev_name = dev_name

    if not args.ws_name:
        args.ws_name = ask_string_input("Please enter workspace name: ")

    # These modes are mutually exclusive
    workspace_modes = ("shared", "tapeout", "regression", "release", "integrator")
    shared_flag = args.shared or args.tapeout or args.regression or args.release

    # if no mode is provided
    if not (shared_flag or args.integrator):
        mode = choose_option(workspace_modes)
        setattr(args, mode, True)

    ws = init_ws_builder(config, args.dev_name, args.integrator, shared=shared_flag)
    ws.test_mode = args.test_mode
    ws.validate_make_join_args(args)

    if shared_flag:
        run_post = ws.create_shared_ws(args.ws_name)
    else:
        run_post = ws.create_ws(args.ws_name)

    if run_post:
        post_ws_builder(config, args, ws, "is ready")
    return 0


@command(
    help="join an existing shared workspace", setup=WS_Builder.setup_make_join_args
)
def join_ws(args: argparse.Namespace, config: ConfigParser) -> int:
    """
    Joins an existing shared SITaR workspace for a project.
    """
    if args.integrator:
        log_error("Cannot join the integrator workspace")

    ws = init_ws_builder(config, args.dev_name, args.integrator)
    ws.validate_make_join_args(args)
    ws.test_mode = args.test_mode

    if ws.join_shared_ws(args.ws_name):
        post_ws_builder(config, args, ws, "is ready")
    return 0


def setup_rm_ws_args(parser: argparse.ArgumentParser):
    parser.add_argument(
        "ws_name",
        help="Specify the name of the workspace",
        type=str,
        metavar="WS_NAME",
        default="",
        nargs="?",
    )


@command(help="remove workspace", setup=setup_rm_ws_args)
def rm_ws(args: argparse.Namespace, config: ConfigParser) -> int:
    """
    Removes an existing SITaR workspace for a project.
    """

    ws_section = f"area:{args.ws_name.lower()}"
    if not args.ws_name or not config.has_section(ws_section):
        log_info("Cannot find workspace %s!" % args.ws_name)
        print("Please choose one of these workspaces:")
        areas = []
        for i, area in enumerate(all_areas(config), 1):
            print(i, area["name"])
            areas.append(area["name"])

        choice = input("(1-{})".format(i))
        ws_section = f"area:{areas[int(choice)-1].lower()}"

    ws = config[ws_section]
    ws_name = ws["name"]
    dev_name = ws["development"]

    log_info(f"Removing workspace {ws_name}...")
    cmd = "sda rm {} -development {} -noconfirm".format(ws_name, dev_name)
    try:
        subprocess.run(cmd, check=True, shell=True)

    except subprocess.CalledProcessError as err:
        log_error(
            f"ERROR: Command failed with exit code {err.returncode}!", exc_info=True
        )

    log_info("Workspace %s was removed." % ws_name)

    cfg = Path(LOCAL_CACHE_FILE).expanduser()
    update_cache(config, cfg, force=True)

    return 0


@command(help="refresh local cache")
def refresh(args: argparse.Namespace, config: ConfigParser) -> int:
    """refresh the locally cached sda developments and areas."""
    cfg = Path(LOCAL_CACHE_FILE).expanduser()
    update_cache(config, cfg, force=True)

    return 0


def setup_set_ws_args(parser: argparse.ArgumentParser):
    parser.add_argument(
        "ws_name",
        help="Specify the name of the workspace / development",
        type=str,
        metavar="WS_NAME",
        default="",
        nargs="?",
    )
    parser.add_argument(
        "-x",
        "--xterm",
        help="Launch XTerm rather than tcsh",
        dest="xterm",
        action="store_true",
    )


def setup_shell(ws_path: str, dev_name: str = None, xterm: bool = False, cmd="") -> int:
    """prepare and start an interactive shell for a workspace."""

    sub_env = os.environ.copy()
    if dev_name:
        sub_env["QC_SYNC_DEVNAME"] = dev_name

    command = ("tcsh -c 'source {}/cshrc.sitar ; {runcmd}'").format(
        SCRIPT_DIR, runcmd="tcsh" if not cmd else cmd
    )

    if xterm:
        command = f"xterm -e {command}"

    try:
        subprocess.run(command, shell=True, cwd=ws_path, env=sub_env)

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as err:
        log_error("ERROR: setting up shell %r" % err, exc_info=True)

    return 0


def filter_workspaces(ws_names_areas: Iterable[Row], ws_filter: str) -> List[str]:
    """
    Utility function used for set_ws function
    Filter Iterable[Row] Workspaces names that starts with word ws_filter
    case insensitive and ingore spaces at word ends .
    """
    if not ws_filter:
        return []

    # strip any spaces at ends
    ws_filter = ws_filter.strip()

    regex_pattern = re.compile(rf"^{ws_filter}", re.IGNORECASE)
    filtered_ws_names = [
        area["name"] for area in ws_names_areas if regex_pattern.search(area["name"])
    ]
    return filtered_ws_names


@command(help="run shell in a workspace", setup=setup_set_ws_args)
def set_ws(args: argparse.Namespace, config: ConfigParser) -> int:
    """prepare and start an interactive shell for a workspace."""
    ws_name = args.ws_name
    ws_section = f"area:{ws_name.lower()}"
    # if not ws_name or not config.has_section(ws_section):
    #     user_name = getpass.getuser()
    #     ws_section = f"area:{ws_name.lower()}_{user_name}"
    #     # if not config.has_section(ws_section):
    #     #     ws_section = f"area:{ws_name.lower()}_v100_{user_name}"
    if not config.has_section(ws_section):

        all_areas_names = [area["name"] for area in all_areas(config)]

        # filter is provided
        if ws_name:
            filtered_areas = filter_workspaces(all_areas(config), ws_name)
        else:
            log_info("Did not provided any workspace name: %s!" % ws_name)
            filtered_areas = all_areas_names

        # No filtered entries
        # Set filtered_areas to all area names so they are displayes as options
        if not filtered_areas:
            log_info(f"Filter {ws_name} is invalid, displaying all areas.")
            filtered_areas = all_areas_names

        print("Please choose one of these workspaces:")
        choice = choose_option(filtered_areas)

        ws_section = f"area:{choice.lower()}"

    ws = config[ws_section]
    ws_name = ws["name"]
    ws_path = ws["path"]
    log_info("Workspace name is %s" % ws_name)
    log_info("Workspace path is %s" % ws_path)
    return setup_shell(ws_path, ws_name, args.xterm)


def setup_shell_args(parser: argparse.ArgumentParser):
    parser.add_argument(
        "-c", "--command", help="Run given command in the shell and exit", dest="cmd"
    )


@command(help="run shell in current workspace", setup=setup_shell_args)
def shell(args: argparse.Namespace, config: ConfigParser) -> int:
    """like set_ws, but infers the project and workspace from cwd."""

    rc_file_dir = get_sitr_root_dir(".shrc.project")
    if not rc_file_dir:
        log_error("Cannot determine current project and/or workspace!")

    return setup_shell(rc_file_dir, cmd=args.cmd)


@command(help="run sda gui")
def gui(args: argparse.Namespace, config: ConfigParser) -> int:
    """launch sda gui and leave it running."""

    cmd = "sda gui &"
    subprocess.run(cmd, shell=True)

    return 0


def add_command_parser(
    commands: argparse.ArgumentParser, func_name: str, func: callable
) -> argparse.ArgumentParser:
    command_parser = commands.add_parser(
        func_name, help=func.__help__, description=func.__doc__
    )
    command_parser.set_defaults(func=func)
    return command_parser


def setup_parse_args():
    parser = argparse.ArgumentParser(
        description="Wrapper script for workspace and project commands"
    )
    parser.add_argument(
        "-I",
        "--interactive",
        help="Bring up the interactive debug shell",
        action="store_true",
    )
    parser.add_argument(
        "-T", "--test_mode", help="Run in test mode", action="store_true"
    )

    commands = parser.add_subparsers(
        metavar="COMMAND", dest="command", help="one of the supported commands below"
    )

    for key, value in globals().items():
        if callable(value) and getattr(value, "__cmd__", None) is True:
            subparser = add_command_parser(commands, key, value)
            setup = getattr(value, "__setup__", None)
            if callable(setup):
                setup(subparser)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    return args


def main():
    logfile = HOME_LOG_FILE / "{script}_{user}.log".format(
        script=SCRIPT_NAME, user=os.environ.get("USER", "nobody")
    )
    fmt = " ".join(("%(asctime)s", "%(levelname)s", "[%(name)s]", "%(message)s"))
    logging.basicConfig(
        filename=logfile,
        filemode="a",
        format=fmt,
        datefmt=ISOFORMAT,
        level=logging.DEBUG,
    )
    handler = logging.handlers.RotatingFileHandler(filename=logfile, backupCount=20)
    file_formatter = logging.Formatter(fmt=fmt, datefmt=ISOFORMAT)
    handler.setFormatter(file_formatter)
    logger.addHandler(handler)
    handler.doRollover()

    logger.info("Logging to %s", logfile)

    args = setup_parse_args()

    # Create the cache initially if missing, but don't do it
    # if the command is refresh, since it will do it anyway.
    config = get_config(skip_update=(args.command == "refresh"))

    if args.interactive:
        import IPython

        IPython.embed()
    elif args.command is not None:
        return args.func(args, config)


if __name__ == "__main__":
    sys.exit(main())
