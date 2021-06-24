"""
Provide functionality for GUI buttons.
TODO : After refactoring have a common API for CLI and GUI
"""

from dm import setup_dmsh, wait_for_shell_with_timeout
from pathlib import Path
from functools import wraps


def shell(func):
    """
    Set up shell , and load module if provided
    """

    @wraps(func)
    def wrapper(module_name=None):
        dssc, _ = setup_dmsh(Path.cwd(), test_mode=False, bsub_mode=False)

        if not module_name:
            module_name = []

        module_name = list(module_name)
        with dssc.shell.run_shell():
            wait_for_shell_with_timeout(dssc.shell)
            dssc.initial_setup()
            dssc.wtf_get_sitr_modules(given_mods=module_name)
            return func(dssc)

    return wrapper


@shell
def wtf_status(dssc):
    mods = dssc.get_sitr_modules()
    # flatten into list of rows
    rows = [[key] + list(mods[key].values()) for key in mods]
    return rows


@shell
def pop_module(dssc):
    return dssc.pop_modules(force=False)


@shell
def restore_module(dssc):
    return dssc.restore()


@shell
def pop_workspace(dssc):
    return dssc.populate(force=False)


@shell
def update(dssc):
    return dssc.update("", False)
