#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper class to manage the MySQL InnoDB cluster lifecycle with MySQL Shell."""

import logging

from ops.model import Container
from ops.pebble import ExecError
from tenacity import retry, stop_after_delay, wait_fixed

logger = logging.getLogger(__name__)


class MySQLInstanceConfigureError(Exception):
    """Exception raised when there is an issue configuring a MySQL instance."""

    pass


class MySQLConfigureMySQLUsersError(Exception):
    """Exception raised when creating a user fails."""

    pass


class MySQL:
    """Class to encapsulate all operations related to the MySQL instance and cluster.

    This class handles the configuration of MySQL instances, and also the
    creation and configuration of MySQL InnoDB clusters via Group Replication.
    """

    def __init__(
        self,
        root_password: str,
        cluster_admin_user: str,
        cluster_admin_password: str,
        instance_address: str,
    ):
        """Initialize the MySQL class.

        Args:
            root_password: password for the 'root' user
            cluster_admin_user: user name for the cluster admin user
            cluster_admin_password: password for the cluster admin user
            instance_address: address of the targeted instance
        """
        self.root_password = root_password
        self.cluster_admin_user = cluster_admin_user
        self.cluster_admin_password = cluster_admin_password
        self.instance_address = instance_address

    def configure_mysql_users(self) -> None:
        """Configure the MySQL users for the instance.

        Creates base `root@%` and `clusteradmin@instance_address` user with the
        appropriate privileges, and reconfigure `root@localhost` user password.
        Raises MySQLConfigureMySQLUsersError if the user creation fails.
        """
        _script = (
            "SET @@SESSION.SQL_LOG_BIN=0;",
            f"CREATE USER '{self.cluster_admin_user}'@'{self.instance_address}' IDENTIFIED BY '{self.cluster_admin_password}';",
            f"GRANT ALL ON *.* TO '{self.cluster_admin_user}'@'{self.instance_address}' WITH GRANT OPTION;",
            f"CREATE USER 'root'@'%' IDENTIFIED BY '{self.root_password}';",
            "GRANT ALL ON *.* TO 'root'@'%' WITH GRANT OPTION;",
            "UPDATE mysql.user SET authentication_string=null WHERE User='root' and Host='localhost';",
            f"ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '{self.root_password}';",
            "REVOKE SYSTEM_USER ON *.* FROM root@'%';",
            "REVOKE SYSTEM_USER ON *.* FROM root@localhost;",
            "FLUSH PRIVILEGES;",
        )

        try:
            self._run_mysqlcli_script(" ".join(_script))
        except ExecError as e:
            logger.exception(f"Failed to configure users for: {self.instance_address}", exc_info=e)
            raise MySQLConfigureMySQLUsersError(e.stdout)

    def configure_instance(self) -> None:
        """Configure the instance to be used in an InnoDB cluster."""
        commands = (
            f"dba.configure_instance('{self.cluster_admin_user}:{self.cluster_admin_password}@{self.instance_address}')",
            f"my_shell = shell.connect('{self.cluster_admin_user}:{self.cluster_admin_password}@{self.instance_address}')",
            'my_shell.run_sql("RESTART;");',
        )

        try:
            logger.debug("Configuring instance for InnoDB")
            self._run_mysqlsh_script("\n".join(commands))

            logger.debug("Waiting until MySQL is restarted")
            self._wait_until_mysql_connection()
        except ExecError as e:
            logger.exception(f"Failed to configure instance: {self.instance_address}", exc_info=e)
            raise MySQLInstanceConfigureError(e.stderr)

    def create_cluster(self) -> None:
        """Create an InnoDB cluster with Group Replication enabled."""
        pass

    def add_instance_to_cluster(self) -> None:
        """Add an instance to the InnoDB cluster."""
        pass

    @retry(reraise=True, stop=stop_after_delay(30), wait=wait_fixed(5))
    def _wait_until_mysql_connection(self) -> None:
        """Wait until a connection to MySQL has been obtained.

        Retry every 5 seconds for 30 seconds if there is an issue obtaining a connection.
        """
        commands = (
            f"my_shell = shell.connect('{self.cluster_admin_user}:{self.cluster_admin_password}@{self.instance_address}')",
        )

        self._run_mysqlsh_script("\n".join(commands))

    def _run_mysqlsh_script(self, script: str, container: Container) -> None:
        """Execute a MySQL shell script.

        Raises ExecError if the script gets a non-zero return code.

        Args:
            script: Mysqlsh script string
            container: Container to run the script in
        """
        process = container.push(path="/tmp/script.sql", source=script)
        process.wait()

        # Specify python as this is not the default in the deb version
        # of the mysql-shell snap
        cmd = ["/usr/bin/mysqlsh", "--no-wizard", "--python", "-f", "/tmp/script.sql"]
        process = container.exec(cmd)
        process.wait()

    def _run_mysqlcli_script(self, script: str, container: Container) -> None:
        """Execute a MySQL CLI script.

        Execute SQL script as instance root user.
        Raises ExecError if the script gets a non-zero return code.

        Args:
            script: raw SQL script string
            container: Container to run the script in
        """
        cmd = [
            "mysql",
            "-u",
            "root",
            "--protocol=SOCKET",
            "--socket=/var/run/mysqld/mysqld.sock",
            "-e",
            script,
        ]
        process = container.exec(cmd)
        process.wait()
