#! /usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""An API connecting charm code to MySQL shell on a MySQL server instance."""
import logging
import secrets
import string
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)


class MySQLConnector:
    """Manages the connection between charm code and MySQL shell commands.

    Args:
        unit: the unit where all commands will run.
    """

    def __init__(self, unit):
        self._unit = unit
        self._container = unit.get_container("mysql-server")
        self._src_dir = Path(__file__).parent

    def configure_server_instance(self) -> None:
        """Pushes configuration and required files to the server container."""
        env = Environment(loader=FileSystemLoader("src"))
        template = env.get_template("server_files/my.cnf")
        rendered = template.render(server_id=str(int(self._unit.name.split("/")[-1]) + 1))
        self._container.push("/etc/mysql/my.cnf", rendered)
        filename = self._src_dir / "server_files/mysqlserver.py"
        with open(filename) as f:
            self._container.push("/root/mysqlserver.py", f)

    def create_innodb_cluster(self, name: str) -> None:
        """Creates a single-unit InnoDB cluster."""
        process = self._container.exec(["mysqlsh", "--pym", "mysqlserver", "createcluster"])
        stdout, stderr = process.wait_output()
        if stdout:
            logger.info(stdout)
        else:
            logger.error(stderr)

    def cluster_status(self):
        """Returns True if the cluster status is OK or similar, False otherwise."""
        process = self._container.exec(["mysql", "--pym", "mysqlserver", "clusterstatus"])
        stdout, stderr = process.wait_output()
        if stdout:
            logger.info(stdout)
        else:
            logger.error(stderr)
        return stdout

    @staticmethod
    def generate_password() -> str:
        """Returns a random 12 characters string that can be used as password."""
        alphanums = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphanums) for _ in range(12))
