#!/pkg/qct/software/python/3.6.0/bin/python
#
# ------------------------------------------------------------------------------
# QUALCOMM Confidential Proprietary
# Copyright (c) 2019, QUALCOMM Incorporated.
# All rights reserved.
#
# Export of this software may be controlled by the United States Government.
# Diversion contrary to U.S. law prohibited.
#
# Licensed Material - Restricted Use.
#
# Restricted Distribution. This document contains critical information about
# QUALCOMM products and may not be distributed to anyone that is not an employee
# of QUALCOMM, its affiliates or subsidiaries without the approval of
# Configuration Management.
#
# Author:        jcoates
# Creation Date: Wed Oct 09 22:33:07 PDT 2019
#
# ------------------------------------------------------------------------------
"""
    Contains the modules for and class for controlling a process as a shell.
    This can be run as a stand-alone script. For a complete list of all of
    the cmd line options:

    ./Process.py -h

    For an interactive shell, you can use the following command:

    ./Process.py -I

    To run the doc test, you can do this:

    ./Process.py -t
"""

import argparse
import os
import queue
import subprocess
import threading
from contextlib import contextmanager

try:
    import log

    LOGGER = log.getLogger(__name__)
except ImportError:
    import logging

    LOGGER = logging.getLogger(__name__)


class Process(object):
    """Class to create an interactive process and run commands and parse response
    This class is used to run a shell like process. There are methods to send
    commands and read the response. There is a separate thread for reading from
    the process and sending output back to the main thread via a queue. The
    read process looks for the prompt associated with the process. The
    interface for the process can work in two different modes, either where
    a command is sent (with a timeout) or streaming.
    Attributes:
        prompt: the string prompt for the process
        init_timeout: initial timeout when starting the process
        timeout: timeout for all commands
        cwd: current working directory for the process
        command: stores the command used to start the process
        start_cmd: initial command to send to the process
        end_cmd: command to shutdown the process
        env: environment variable used for the process
        queue: queue for the responses coming from the process
        thread: stores the handle for the read thread
        read_running: bool that indicates that the read is running
        stream: bool that is true when streaming output

    Examples:
        >>> import dm
        >>> sh = dm.Process(command="/bin/cat")
        >>> sh.prompt = "> "
        >>> sh.timeout = 1
        >>> sh.cwd = "/tmp"
        >>> sh.env = {'TEST': '123'}
        >>> with sh.run_shell():
        ...   sh.send_command(sh.prompt)
        ...   if sh.wait_for_shell():
        ...     resp = sh.run_command(f"command 2{sh.prompt}")
        ...     sh.send_command(f"command 1{sh.prompt}")
        ...     resp2 = sh.get_response()
        ...
        >>> resp
        'command 2'
        >>> resp2.lstrip()
        'command 1> '"""

    def __init__(
        self,
        command: str = None,
        prompt: str = "%",
        cwd: str = ".",
        timeout: int = 1,
        init_timeout: int = 10,
        start_cmd: str = None,
        end_cmd: str = None,
        env=None,
    ) -> None:
        """Initializer for the Process class"""
        self.prompt = prompt
        self.init_timeout = init_timeout
        self.timeout = timeout
        self.cwd = cwd
        self.command = command
        self._debug_thread = False
        self.start_cmd = start_cmd
        self.end_cmd = end_cmd
        self.env = env if env else {}

        self.queue = None
        self.thread = None
        # TODO - do we need this?
        self._lock = threading.Lock()
        self.read_running = False
        self.stream = False

    def read_output(self) -> str:
        """runs a separate thread reading stdout from the process"""
        output = ""
        # TODO - add a lock for this?
        self.read_running = True
        while True:
            data = self.process.stdout.read(1).decode("utf-8")
            if not data:
                # TODO - need to handle this case better
                self.read_running = False
                LOGGER.warn(f"WARNING! Read thread terminating")
                return
            output += data
            if self._debug_thread:
                print(data, end="")
            if output.endswith(self.prompt) or (self.stream and output.endswith("\n")):
                self.queue.put(output)
                output = ""
        self.read_running = False
        return

    # TODO - how to shutdown?
    def get_response(self, timeout: int = 0, test_mode: bool = False) -> str:
        """returns a process response that is in the queue, can through a queue.Empty exception on timeout"""
        if test_mode:
            return ""

        if not timeout:
            timeout = self.timeout
        # Throws queue.Empty
        return self.queue.get(block=True, timeout=timeout)

    def get_response_no_timeout(self, test_mode: bool = False) -> str:
        """returns a process response that is in the queue, will wait indefinitely"""
        if test_mode:
            return ""
        return self.queue.get(block=True)

    def process_up(self) -> bool:
        """used to check to see if the process is up and running"""
        self.send_command("")
        if self.get_response():
            return True
        return False

    def send_command(self, cmd: str, test_mode: bool = False) -> None:
        """sends a command to the process without blocking"""
        while not self.queue.empty():
            resp = self.queue.get()
            LOGGER.warn(f"WARNING! purging output {resp}")

        if test_mode:
            LOGGER.info(f"cmd = {cmd}")
        else:
            LOGGER.debug(f"cmd = {cmd}")
            cmd += "\n"
            self.process.stdin.write(cmd.encode())
            self.process.stdin.flush()

    def run_command(self, cmd: str, test_mode: bool = False) -> str:
        """run the specified command and return the response"""
        # print(f"Send command {cmd}")
        self.send_command(cmd, test_mode)
        resp = self.get_response(test_mode=test_mode)
        return resp.rstrip(self.prompt).strip()

    def stream_command(self, cmd: str, test_mode: bool = False) -> str:
        """generator used to stream the specified command"""
        self.stream = True
        LOGGER.debug(f"Send command {cmd}")
        self.send_command(cmd, test_mode)
        resp = ""
        if test_mode:
            raise StopIteration

        while not resp.endswith(self.prompt):
            resp = self.get_response_no_timeout()
            yield resp

        self.stream = False
        raise StopIteration

    def run_output(self, command: str) -> None:
        """runs command, printing output, except last line (prompt)"""
        response = self.run_command(command)
        print("\n".join(response.strip().splitlines()[:-1]))

    def stream_command_disp(self, cmd: str, test_mode: bool = False) -> None:
        """stream the specified command"""
        for resp in self.stream_command(cmd, test_mode):
            print(f"{resp}", end="")

    # def set_env(self, env_vars: Dict) -> None:
    #    # TODO - merge?
    #    self.env = env_vars

    # def set_cwd(self, cwd: str) -> None:
    #    self.cwd = cwd

    @contextmanager
    def run_shell(self) -> None:
        """context manager for running the process shell, starts the process, then shuts it down afterwards"""
        try:
            sub_env = os.environ.copy()
            for var in self.env:
                sub_env[var] = self.env[var]
            LOGGER.debug(f"Running the process {self.command}")
            self.process = subprocess.Popen(
                self.command,
                cwd=self.cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=True,
                env=sub_env,
            )
            self.queue = queue.Queue()
            self.thread = threading.Thread(target=self.read_output)
            self.thread.daemon = True
            self.thread.start()
            if self.start_cmd:
                self.send_command(self.start_cmd)
            yield
        except:
            # TODO - how to capture the error?
            # TODO - anything to back out
            LOGGER.exception(f"Exception from run_shell")
            if self.end_cmd:
                self.send_command(self.end_cmd)
            raise
        else:
            LOGGER.debug(f"Shutting down")
            if self.end_cmd:
                self.send_command(self.end_cmd)

    # TODO - add timeout
    def wait_for_shell(self) -> bool:
        """called within the run_shell context manager to wait for the initial prompt"""
        try:
            resp = self.get_response(self.init_timeout)
            return True
        except queue.Empty:
            return False

    def __repr__(self) -> str:
        """Return the string representation of the object"""
        return f"{type(self).__name__}{(self.command, self.prompt, self.cwd)}"


def main():
    """Main routine that is invoked when you run the script"""
    parser = argparse.ArgumentParser(
        description="Script to test out the Process class.",
        add_help=True,
        argument_default=None,  # Global argument default
    )
    parser.add_argument(
        "-d", "--debug", action="store_true", help="enable debug outputs"
    )
    parser.add_argument(
        "-I", "--interactive", action="store_true", help="enable an interactive session"
    )
    parser.add_argument("-t", "--test", action="store_true", help="run the doc tester")
    args = parser.parse_args()

    if args.debug:
        log.set_debug()
    # if args.debug:
    #     log.basicConfig(level=logging.DEBUG)
    # else:
    #     log.basicConfig(level=logging.INFO)

    if args.test:
        import doctest

        doctest.testmod()

    # sh = Process(command="/bin/cat")
    sh = Process(command="/usr/bin/tclsh")
    sh._debug_thread = True
    sh.prompt = "% "
    sh.start_cmd = f'puts "{sh.prompt}"'
    sh.timeout = 1
    sh.cwd = "/tmp"
    sh.env = {"TEST": "123"}
    with sh.run_shell():
        # resp = sh.run_command(f"Hello World\n{sh.prompt}")

        if args.interactive:
            import IPython  # type: ignore

            IPython.embed()  # jump to ipython shell


if __name__ == "__main__":
    main()
