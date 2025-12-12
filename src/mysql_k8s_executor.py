# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper class to manage the MySQL Shell executor."""

import json
import re

import ops
from mysql_shell.executors import BaseExecutor
from mysql_shell.executors.errors import ExecutionError
from mysql_shell.models import ConnectionDetails
from ops.model import Container


class ContainerExecutor(BaseExecutor):
    """Container executor for the MySQL Shell."""

    def __init__(self, conn_details: ConnectionDetails, shell_path: str):
        """Initialize the executor."""
        super().__init__(conn_details, shell_path)
        self._container = None

    def _common_args(self) -> list[str]:
        """Return the list of common arguments."""
        return [
            self._shell_path,
            "--json=raw",
            "--save-passwords=never",
            "--passwords-from-stdin",
        ]

    def _connection_args(self) -> list[str]:
        """Return the list of connection arguments."""
        if self._conn_details.socket:
            return [
                f"--socket={self._conn_details.socket}",
                f"--user={self._conn_details.username}",
            ]
        else:
            return [
                f"--host={self._conn_details.host}",
                f"--port={self._conn_details.port}",
                f"--user={self._conn_details.username}",
            ]

    @staticmethod
    def _parse_error(output: str) -> str:
        """Parse the error message."""
        # MySQL Shell always prompts for the user password
        return output.split("\n")[1]

    @staticmethod
    def _parse_output(output: str) -> dict:
        """Parse the error message."""
        # MySQL Shell always prompts for the user password
        output = output.split("\n")[1]
        output = json.loads(output)
        return output

    @staticmethod
    def _strip_password(error: ops.pebble.Error):
        """Strip passwords from SQL scripts."""
        if not hasattr(error, "command"):
            return error

        password_pattern = re.compile("(?<=IDENTIFIED BY ')[^']+(?=')")
        password_replace = "*****"  # noqa: S105

        for index, value in enumerate(error.command):
            if "IDENTIFIED" in value:
                error.command[index] = re.sub(password_pattern, password_replace, value)

        return error

    def set_container(self, container: Container) -> None:
        """Set the executor container."""
        self._container = container

    def check_connection(self) -> None:
        """Check the connection."""
        command = [
            *self._common_args(),
            *self._connection_args(),
        ]

        try:
            process = self._container.exec(
                command,
                stdin=self._conn_details.password,
                combine_stderr=True,
            )
            process.wait_output()
        except ops.pebble.ExecError as exc:
            err = self._parse_error(exc.stdout)
            raise ExecutionError(err) from exc
        except ops.pebble.TimeoutError as exc:
            raise ExecutionError() from exc

    def execute_py(self, script: str, *, timeout: int | None = None) -> str:
        """Execute a Python script.

        Arguments:
            script: Python script to execute
            timeout: Optional timeout seconds

        Returns:
            String with the output of the MySQL Shell command.
            The output cannot be parsed to JSON, as the output depends on the script
        """
        # Prepend every Python command with useWizards=False, to disable interactive mode.
        # Cannot be set on command line as it conflicts with --passwords-from-stdin.
        script = "shell.options.set('useWizards', False)\n" + script

        command = [
            *self._common_args(),
            *self._connection_args(),
            "--py",
            "--execute",
            script,
        ]

        try:
            process = self._container.exec(
                command,
                timeout=timeout,
                stdin=self._conn_details.password,
                combine_stderr=True,
            )
            stdout, _ = process.wait_output()
        except ops.pebble.ExecError as exc:
            err = self._parse_error(exc.stdout)
            raise ExecutionError(err) from exc
        except ops.pebble.TimeoutError as exc:
            raise ExecutionError() from exc
        else:
            result = self._parse_output(stdout)
            result = result.get("info", "")
            return result.strip()

    def execute_sql(self, script: str, *, timeout: int | None = None) -> list[dict]:
        """Execute a SQL script.

        Arguments:
            script: SQL script to execute
            timeout: Optional timeout seconds

        Returns:
            List of dictionaries, one per returned row
        """
        command = [
            *self._common_args(),
            *self._connection_args(),
            "--sql",
            "--execute",
            script,
        ]

        try:
            process = self._container.exec(
                command,
                timeout=timeout,
                stdin=self._conn_details.password,
                combine_stderr=True,
            )
            stdout, _ = process.wait_output()
        except ops.pebble.ExecError as exc:
            err = self._parse_error(exc.stdout)
            exc = self._strip_password(exc)
            raise ExecutionError(err) from exc
        except ops.pebble.TimeoutError as exc:
            exc = self._strip_password(exc)
            raise ExecutionError() from exc
        else:
            result = self._parse_output(stdout)
            result = result.get("rows", [])
            return result
