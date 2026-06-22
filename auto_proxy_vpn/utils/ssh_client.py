from pathlib import Path
from shlex import quote
from subprocess import run

SSH_EXECUTABLE = "/usr/bin/ssh" if Path("/usr/bin/ssh").exists() else "ssh"
SCP_EXECUTABLE = "/usr/bin/scp" if Path("/usr/bin/scp").exists() else "scp"


class SSHClient:
    """Client for executing commands and downloading files over SSH.

    Parameters
    ----------
    ip : str
        The IP address of the remote server.
    user : str
        The username to use for the SSH connection.
    strict : bool
        Whether to use strict host key checking. If False, it will not check
        the host key and will automatically add it to the known hosts.
        Defaults to ``False``.
    """

    def __init__(
        self,
        ip: str,
        user: str,
        strict: bool = False,
        timeout: int = 30,
    ):
        self.ip = ip
        self.user = user
        self.timeout = timeout
        # No strict host key Checking if strict = False
        self.ssh_args = [SSH_EXECUTABLE]
        if not strict:
            self.ssh_args.extend(["-o", "StrictHostKeyChecking=no"])
        self.ssh_args.append(f"{user}@{ip}")
        self.ssh_command = " ".join(self.ssh_args)

    def connect(self):
        """
        Checks server ssh connection
        """
        result = run(
            [*self.ssh_args, "echo OK"],
            capture_output=True,
            timeout=self.timeout,
        )
        stdout = result.stdout.decode()
        if "OK" in stdout:
            self.active = True
            return True
        return False

    def run_command(self, command: str) -> tuple[int, str, str]:
        """Executes a command in remote server

        Parameters
        ----------
        command : str
            Command to execute.

        Returns
        -------
        tuple[int, str, str]
            Return the returncode, stdout and stderr of the command execution.

        Raises
        ------
        ConnectionError
            If the connection to the server is not active.
        """
        # Check if the connection is alive before trying to run a command
        if not self.connect():
            raise ConnectionError("Can't connect to the server!")

        result = run(
            [*self.ssh_args, command],
            capture_output=True,
            timeout=self.timeout,
        )

        return result.returncode, result.stdout.decode(), result.stderr.decode()

    def download_file(self, file: str, destination_file: str):
        """
        Downloads a file from the remote server to the local machine.

        Parameters
        ----------
        file : str
            The path to the file on the remote server.
        destination_file : str
            The path to save the file on the local machine.

        Raises
        ------
        ConnectionError
            If the connection to the server is not active.
        FileNotFoundError
            If the file does not exist on the remote server.
        """
        # chech if the file exists
        returncode, _, stderror = self.run_command(f"test -f -- {quote(file)}")
        if returncode != 0:
            ssh_errors = ("permission denied", "connection", "host key")
            if any(error in stderror.lower() for error in ssh_errors):
                raise ConnectionError("Can't connect to the server!")
            raise FileNotFoundError("This file doesn't exist in the server")
        if stderror:
            raise ConnectionError("Can't connect to the server!")

        result = run(
            [SCP_EXECUTABLE, f"{self.user}@{self.ip}:{quote(file)}", destination_file],
            capture_output=True,
            timeout=self.timeout,
        )
        if result.returncode:
            raise ConnectionError("Can't download the file from the server!")
