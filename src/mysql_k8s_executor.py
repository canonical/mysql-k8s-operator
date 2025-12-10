# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper class to manage the MySQL Shell executor."""

import json
import re
from typing import Generator

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

    def _parse_error(self, output: str) -> dict:
        """Parse the execution error."""
        error = next(self._iter_output(output, "error"), None)
        if not error:
            error = {}

        return error

    def _parse_output_py(self, output: str) -> str:
        """Parse the Python execution output."""
        result = next(self._iter_output(output, "info"), None)
        if not result:
            result = "{}"

        return result

    def _parse_output_sql(self, output: str) -> list:
        """Parse the SQL execution output."""
        result = next(self._iter_output(output, "rows"), None)
        if not result:
            result = []

        return result

    @staticmethod
    def _iter_output(output: str, key: str) -> Generator:
        """Iterates over the log lines in reversed order."""
        logs = output.split("\n")

        # MySQL Shell always prints prompts and warnings first
        for log in reversed(logs):
            if not log:
                continue

            log = json.loads(log)
            val = log.get(key)
            if not isinstance(val, str) or val.strip():
                yield val

    @staticmethod
    def _strip_password(error: ops.pebble.Error):
        """Strip passwords from SQL scripts."""
        if not hasattr(error, "command"):
            return error

        password_pattern = re.compile("(?<=IDENTIFIED BY ')[^']+(?=')")
        password_replace = "*****"  # noqa: S105

        for index, value in enumerate(error.command):
            if "IDENTIFIED BY" in value:
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
            )
            stdout, _ = process.wait_output()
        except ops.pebble.ExecError as exc:
            err = self._parse_error(exc.stdout)
            raise ExecutionError(err) from exc
        except ops.pebble.TimeoutError as exc:
            raise ExecutionError() from exc
        else:
            return self._parse_output_py(stdout)

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
            return self._parse_output_sql(stdout)
