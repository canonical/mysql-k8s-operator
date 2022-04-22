#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper class to manage the MySQL InnoDB cluster lifecycle with MySQL Shell."""

import json
import logging

from ops.model import Container
from ops.pebble import ExecError
from tenacity import retry, stop_after_delay, wait_fixed

logger = logging.getLogger(__name__)

MYSQLD_SOCK_FILE = "/var/run/mysqld/mysqld.sock"
MYSQLSH_SCRIPT_FILE = "/tmp/script.py"
MYSQLD_CONFIG_PATH = "/etc/mysql/conf.d/z-custom-mysqld.cnf"

GROUP_REPLICATION_PORT = 33061


class MySQLConfigureInstanceError(Exception):
    """Exception raised when there is an issue configuring a MySQL instance."""

    pass


class MySQLConfigureMySQLUsersError(Exception):
    """Exception raised when creating a user fails."""

    pass


class MySQLServiceNotRunningError(Exception):
    """Exception raised when the MySQL service is not running."""

    pass


class MySQLCreateClusterError(Exception):
    """Exception raised when there is an issue creating an InnoDB cluster."""

    pass


class MySQLAddInstanceToClusterError(Exception):
    """Exception raised when there is an issue add an instance to the MySQL InnoDB cluster."""

    pass


class MySQLBootstrapInstanceError(Exception):
    """Exception raised when there is an issue bootstrapping an instance."""

    pass


class MySQLPatchDNSSearchesError(Exception):
    """Exception raised when there is an issue patching the DNS searches."""

    pass


class MySQL:
    """Class to encapsulate all operations related to the MySQL instance and cluster.

    This class handles the configuration of MySQL instances, and also the
    creation and configuration of MySQL InnoDB clusters via Group Replication.
    """

    def __init__(
        self,
        instance_address: str,
        cluster_name: str,
        root_password: str,
        server_config_user: str,
        server_config_password: str,
        cluster_admin_user: str,
        cluster_admin_password: str,
        container: Container,
    ):
        """Initialize the MySQL class.

        Args:
            instance_address: address of the targeted instance
            cluster_name: cluster name
            root_password: password for the 'root' user
            server_config_user: user name for the server config user
            server_config_password: password for the server config user
            cluster_admin_user: user name for the cluster admin user
            cluster_admin_password: password for the cluster admin user
            container: workload container object
        """
        self.instance_address = instance_address
        self.cluster_name = cluster_name
        self.root_password = root_password
        self.server_config_user = server_config_user
        self.server_config_password = server_config_password
        self.cluster_admin_user = cluster_admin_user
        self.cluster_admin_password = cluster_admin_password
        self.container = container

    def bootstrap_instance(self) -> None:
        """Execute instance first run.

        Initialise mysql data directory and create blank password root@localhost user.
        Raises MySQLBootstrapInstanceError if the instance bootstrap fails.
        """
        bootstrap_command = ["mysqld", "--initialize-insecure", "-u", "mysql"]

        try:
            process = self.container.exec(command=bootstrap_command)
            process.wait_output()
        except ExecError as e:
            logger.error("Exited with code %d. Stderr:", e.exit_code)
            if e.stderr:
                for line in e.stderr.splitlines():
                    logger.error("  %s", line)
            raise MySQLBootstrapInstanceError(e.stderr if e.stderr else "")

    def patch_dns_searches(self, app_name: str) -> None:
        """Patch the DNS searches to allow the instance to be discovered.

        Raises MySQLPatchDNSSearchesError if the patching fails.
        FIXME: Fix this to use the proper k8s name resolution.
                MySQL instance are not using `group_replication_local_address`
                to report own address to the cluster, hence this hack.

        Args:
            app_name: name of the application
        """
        try:
            resolv_file = self.container.pull("/etc/resolv.conf")
            content = resolv_file.read()
            output_string = ""
            for line in content.splitlines():
                line_content = line.split()
                if line_content[0] == "search":
                    line_content[1:1] = [f"{app_name}-endpoints.{line_content[1]}"]
                    output_string += " ".join(line_content) + "\n"
                else:
                    output_string += line + "\n"
            self.container.push("/etc/resolv.conf-new", source=output_string)
            process = self.container.exec(["cp", "/etc/resolv.conf-new", "/etc/resolv.conf"])
            process.wait()
        except Exception:
            raise MySQLPatchDNSSearchesError()

    def configure_mysql_users(self) -> None:
        """Configure the MySQL users for the instance.

        Creates base `root@%` and `<server_config>@%` users with the
        appropriate privileges, and reconfigure `root@localhost` user password.

        Raises MySQLConfigureMySQLUsersError if the user creation fails.
        """
        # SYSTEM_USER and SUPER privileges to revoke from the root users
        # Reference: https://dev.mysql.com/doc/refman/8.0/en/privileges-provided.html#priv_super
        privileges_to_revoke = (
            "SYSTEM_USER",
            "SYSTEM_VARIABLES_ADMIN",
            "SUPER",
            "REPLICATION_SLAVE_ADMIN",
            "GROUP_REPLICATION_ADMIN",
            "BINLOG_ADMIN",
            "SET_USER_ID",
            "ENCRYPTION_KEY_ADMIN",
            "VERSION_TOKEN_ADMIN",
            "CONNECTION_ADMIN",
        )

        # Configure root@%, root@localhost and serverconfig@% users
        configure_users_commands = (
            f"CREATE USER 'root'@'%' IDENTIFIED BY '{self.root_password}';",
            "GRANT ALL ON *.* TO 'root'@'%' WITH GRANT OPTION;",
            f"CREATE USER '{self.server_config_user}'@'%' IDENTIFIED BY '{self.server_config_password}';",
            f"GRANT ALL ON *.* TO '{self.server_config_user}'@'%' WITH GRANT OPTION;",
            "UPDATE mysql.user SET authentication_string=null WHERE User='root' and Host='localhost';",
            f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{self.root_password}';",
            f"REVOKE {', '.join(privileges_to_revoke)} ON *.* FROM 'root'@'%';",
            f"REVOKE {', '.join(privileges_to_revoke)} ON *.* FROM 'root'@'localhost';",
            "FLUSH PRIVILEGES;",
        )

        try:
            logger.debug("Configuring users")
            self._run_mysqlcli_script(" ".join(configure_users_commands))
        except ExecError as e:
            logger.error("Exited with code %d. Stderr:", e.exit_code)
            if e.stderr:
                for line in e.stderr.splitlines():
                    logger.error("  %s", line)
            raise MySQLConfigureMySQLUsersError(e.stderr if e.stderr else "")

    def configure_instance(self) -> None:
        """Configure the instance to be used in an InnoDB cluster.

        Raises MySQLConfigureInstanceError if the instance configuration fails.
        """
        # mysqld daemon cannot be restarted automatically
        # which requires a container restart after configuration
        options = {
            "clusterAdmin": self.cluster_admin_user,
            "clusterAdminPassword": self.cluster_admin_password,
            "restart": "false",
        }
        configure_instance_command = (
            f"dba.configure_instance('{self.server_config_user}:{self.server_config_password}@{self.instance_address}', {json.dumps(options)})",
        )

        try:
            logger.debug("Configuring instance for group replication")
            self._run_mysqlsh_script("\n".join(configure_instance_command))
            # restart the pebble layer service
            self.container.restart("mysqld")
            logger.debug("Waiting until MySQL to restart")
            self._wait_until_mysql_connection()
        except ExecError as e:
            logger.error("Exited with code %d.", e.exit_code)
            if e.stderr:
                for line in e.stderr.splitlines():
                    logger.error("  %s", line)
            raise MySQLConfigureInstanceError(e.stderr if e.stderr else "")

    def create_cluster(self) -> None:
        """Create an InnoDB cluster with Group Replication enabled.

        Raises MySQLCreateClusterError if there was an issue creating the cluster.
        """
        replication_commands = (
            f"shell.connect('{self.server_config_user}:{self.server_config_password}@{self.instance_address}')",
            f"dba.create_cluster('{self.cluster_name}')",
        )

        # Run the script that enables Group Replication for the instance
        try:
            logger.debug("Creating a MySQL InnoDB cluster")
            self._run_mysqlsh_script("\n".join(replication_commands))
        except ExecError as e:
            logger.error("Exited with code %d.", e.exit_code)
            if e.stderr:
                for line in e.stderr.splitlines():
                    logger.error("  %s", line)
            raise MySQLCreateClusterError(e.stderr if e.stderr else "")

    def add_instance_to_cluster(self, instance_address) -> None:
        """Add an instance to the InnoDB cluster.

        Try to add instance with recoveryMethod "auto". If that fails, try with "clone".
        Raises MySQLADDInstanceToClusterError
            if there was an issue adding the instance to the cluster.

        Args:
            instance_address: address of the instance to be added
        """
        options = {
            "password": self.cluster_admin_password,
        }

        connect_commands = (
            f"shell.connect('{self.cluster_admin_user}:{self.cluster_admin_password}@{self.instance_address}')",
            f"cluster = dba.get_cluster('{self.cluster_name}')",
        )

        for recovery_method in ["auto", "clone"]:
            # Prefer "auto" recovery method, but if it fails, try "clone"
            try:
                options["recoveryMethod"] = recovery_method
                add_instance_command = (
                    f"cluster.add_instance('{self.cluster_admin_user}@{instance_address}', {json.dumps(options)})",
                )

                logger.debug(
                    f"Adding instance {instance_address} to cluster {self.cluster_name} with recovery method {recovery_method}"
                )
                self._run_mysqlsh_script("\n".join(connect_commands + add_instance_command))

                break

            except ExecError as e:
                if recovery_method == "clone":
                    logger.exception(
                        f"Failed to add instance {instance_address} to cluster {self.cluster_name} on {self.instance_address}",
                        exc_info=e,
                    )
                    raise MySQLAddInstanceToClusterError(e.stderr if e.stderr else "")

                logger.debug(
                    f"Failed to add instance {instance_address} to cluster {self.cluster_name} with recovery method 'auto'. Trying method 'clone'"
                )

    @retry(reraise=True, stop=stop_after_delay(30), wait=wait_fixed(5))
    def _wait_until_mysql_connection(self) -> None:
        """Wait until a connection to MySQL daemon is possible.

        Retry every 5 seconds for 30 seconds if there is an issue obtaining a connection.
        """
        if not self.container.exists(MYSQLD_SOCK_FILE):
            raise MySQLServiceNotRunningError()

    def _run_mysqlsh_script(self, script: str) -> None:
        """Execute a MySQL shell script.

        Raises ExecError if the script gets a non-zero return code.

        Args:
            script: mysql-shell python script string
        """
        self.container.push(path=MYSQLSH_SCRIPT_FILE, source=script)

        # render command with remove file after run
        cmd = [
            "/usr/bin/mysqlsh",
            "--no-wizard",
            "--python",
            "--verbose=1",
            "-f",
            MYSQLSH_SCRIPT_FILE,
            ";",
            "rm",
            MYSQLSH_SCRIPT_FILE,
        ]
        process = self.container.exec(cmd)
        process.wait_output()

    def _run_mysqlcli_script(self, script: str, password: str = None, user: str = "root") -> None:
        """Execute a MySQL CLI script.

        Execute SQL script as instance root user.
        Raises ExecError if the script gets a non-zero return code.

        Args:
            script: raw SQL script string
            password: root password to use for the script when needed
            user: user to run the script
        """
        command = [
            "/usr/bin/mysql",
            "-u",
            user,
            "--protocol=SOCKET",
            f"--socket={MYSQLD_SOCK_FILE}",
            "-e",
            script,
        ]
        if password:
            # password is needed after user
            command.append(f"--password={password}")
        process = self.container.exec(command)
        process.wait_output()
