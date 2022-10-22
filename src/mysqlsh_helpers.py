#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper class to manage the MySQL InnoDB cluster lifecycle with MySQL Shell."""

import json
import logging
import os

from charms.mysql.v0.mysql import (
    MySQLBase,
    MySQLClientError,
    MySQLConfigureInstanceError,
    MySQLConfigureMySQLUsersError,
)
from ops.model import Container
from ops.pebble import ExecError
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    retry_if_result,
    stop_after_attempt,
    stop_after_delay,
    wait_fixed,
    wait_random,
)

logger = logging.getLogger(__name__)

MYSQLD_SOCK_FILE = "/var/run/mysqld/mysqld.sock"
MYSQLSH_SCRIPT_FILE = "/tmp/script.py"
MYSQLD_CONFIG_FILE = "/etc/mysql/conf.d/z-report-host-custom.cnf"
MYSQL_SYSTEM_USER = "mysql"
MYSQL_DATA_DIR = "/var/lib/mysql"
MYSQLD_CONFIG_DIRECTORY = "/etc/mysql/conf.d"


class MySQLInitialiseMySQLDError(Exception):
    """Exception raised when there is an issue initialising an instance."""


class MySQLServiceNotRunningError(Exception):
    """Exception raised when the MySQL service is not running."""


class MySQLCreateCustomConfigFileError(Exception):
    """Exception raised when there is an issue creating custom config file."""


class MySQLRemoveInstancesNotOnlineError(Exception):
    """Exception raised when there is an issue removing not online instances."""


class MySQLRemoveInstancesNotOnlineRetryError(Exception):
    """Exception raised when retry required for remove_instances_not_online."""


class MySQLCreateDatabaseError(Exception):
    """Exception raised when there is an issue creating a database."""


class MySQLCreateUserError(Exception):
    """Exception raised when there is an issue creating a user."""


class MySQLEscalateUserPrivilegesError(Exception):
    """Exception raised when there is an issue escalating user privileges."""


class MySQLDeleteUsersWithLabelError(Exception):
    """Exception raised when there is an issue deleting users with a label."""


class MySQL(MySQLBase):
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
        super().__init__(
            instance_address=instance_address,
            cluster_name=cluster_name,
            root_password=root_password,
            server_config_user=server_config_user,
            server_config_password=server_config_password,
            cluster_admin_user=cluster_admin_user,
            cluster_admin_password=cluster_admin_password,
        )
        self.container = container

    @staticmethod
    def get_mysqlsh_bin() -> str:
        """Determine binary path for MySQL Shell.

        Returns:
            Path to binary mysqlsh
        """
        # Allow for various versions of the mysql-shell snap
        # When we get the alias use /snap/bin/mysqlsh
        paths = ("/usr/bin/mysqlsh", "/snap/bin/mysqlsh", "/snap/bin/mysql-shell.mysqlsh")

        for path in paths:
            if os.path.exists(path):
                return path

        # Default to the full path version
        return "/snap/bin/mysql-shell"

    def initialise_mysqld(self) -> None:
        """Execute instance first run.

        Initialise mysql data directory and create blank password root@localhost user.
        Raises MySQLInitialiseMySQLDError if the instance bootstrap fails.
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
            raise MySQLInitialiseMySQLDError(e.stderr if e.stderr else "")

    @retry(reraise=True, stop=stop_after_delay(30), wait=wait_fixed(5))
    def wait_until_mysql_connection(self) -> None:
        """Wait until a connection to MySQL daemon is possible.

        Retry every 5 seconds for 30 seconds if there is an issue obtaining a connection.
        """
        if not self.container.exists(MYSQLD_SOCK_FILE):
            raise MySQLServiceNotRunningError()

    def configure_instance(self) -> None:
        """Configure the instance to be used in an InnoDB cluster.

        Raises MySQLConfigureInstanceError if the instance configuration fails.
        """
        try:
            super(MySQL, self).configure_instance(restart=False)

            # restart the pebble layer service
            self.container.restart("mysqld")
            logger.debug("Waiting until MySQL to restart")
            self.wait_until_mysql_connection()

            # set global variables to enable group replication in k8s
            self._set_group_replication_initial_variables()
        except (
            MySQLClientError,
            MySQLServiceNotRunningError,
        ) as e:
            logger.exception(
                "Failed to configure instance for use in an InnoDB cluster", exc_info=e
            )
            raise MySQLConfigureInstanceError(e.message)

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
            f"CREATE USER 'root'@'%' IDENTIFIED BY '{self.root_password}'",
            "GRANT ALL ON *.* TO 'root'@'%' WITH GRANT OPTION",
            f"CREATE USER '{self.server_config_user}'@'%' IDENTIFIED BY '{self.server_config_password}'",
            f"GRANT ALL ON *.* TO '{self.server_config_user}'@'%' WITH GRANT OPTION",
            "UPDATE mysql.user SET authentication_string=null WHERE User='root' and Host='localhost'",
            f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{self.root_password}'",
            f"REVOKE {', '.join(privileges_to_revoke)} ON *.* FROM 'root'@'%'",
            f"REVOKE {', '.join(privileges_to_revoke)} ON *.* FROM 'root'@'localhost'",
            "FLUSH PRIVILEGES",
        )

        try:
            logger.debug("Configuring users")
            self._run_mysqlcli_script("; ".join(configure_users_commands))
        except MySQLClientError as e:
            logger.exception("Error configuring MySQL users", exc_info=e)
            raise MySQLConfigureMySQLUsersError(e.message)

    def _set_group_replication_initial_variables(self) -> None:
        """Install the group replication plugin and set initial variables.

        Necessary for k8s deployments.
        Raises MySQLClientError if the script gets a non-zero return code.
        """
        commands = (
            "INSTALL PLUGIN group_replication SONAME 'group_replication.so'",
            f"SET PERSIST group_replication_local_address='{self.instance_address}:33061'",
            "SET PERSIST group_replication_ip_allowlist='0.0.0.0/0,::/0'",
        )

        self._run_mysqlcli_script(
            "; ".join(commands), self.cluster_admin_password, self.cluster_admin_user
        )

    def create_custom_config_file(self, report_host: str) -> None:
        """Create custom configuration file.

        Necessary for k8s deployments.
        Raises MySQLCreateCustomConfigFileError if the script gets a non-zero return code.
        """
        content = ("[mysqld]", f"report_host = {report_host}", "")

        try:
            self.container.push(MYSQLD_CONFIG_FILE, source="\n".join(content))
        except Exception:
            raise MySQLCreateCustomConfigFileError()

    @retry(
        retry=retry_if_result(lambda x: not x),
        stop=stop_after_attempt(10),
        wait=wait_fixed(60),
    )
    def _wait_till_all_members_are_online(self) -> None:
        """Wait until all members of the cluster are online.

        Retries every minute for 10 minute if not all members are online.

        Raises:
            RetryError - if timeout reached before all members are online.
        """
        cluster_status = self.get_cluster_status()

        online_members = [
            label
            for label, member in cluster_status["defaultreplicaset"]["topology"].items()
            if member["status"] == "online"
        ]

        return len(online_members) == len(cluster_status["defaultreplicaset"]["topology"])

    def _remove_unreachable_instances(self) -> None:
        """Removes all unreachable instances in the cluster."""
        cluster_status = self.get_cluster_status()
        if not cluster_status:
            raise MySQLRemoveInstancesNotOnlineRetryError("Unable to retrieve cluster status")

        # Remove each member that is not online or recovering
        # All member status available at
        # https://dev.mysql.com/doc/mysql-shell/8.0/en/monitoring-innodb-cluster.html
        not_online_members_addresses = [
            member["address"]
            for _, member in cluster_status["defaultreplicaset"]["topology"].items()
            if member["status"] not in ["online", "recovering"]
        ]
        for member_address in not_online_members_addresses:
            logger.info(f"Removing unreachable member {member_address} from the cluster")

            remove_instance_options = {
                "force": "true",
            }
            remove_instance_commands = (
                f"shell.connect('{self.cluster_admin_user}:{self.cluster_admin_password}@{self.instance_address}')",
                f"cluster = dba.get_cluster('{self.cluster_name}')",
                f"cluster.remove_instance('{member_address}', {json.dumps(remove_instance_options)})",
            )

            self._run_mysqlsh_script("\n".join(remove_instance_commands))

    @retry(
        retry=retry_if_exception_type(MySQLRemoveInstancesNotOnlineRetryError),
        stop=stop_after_attempt(3),
        reraise=True,
        wait=wait_random(min=4, max=30),
    )
    def remove_instances_not_online(self) -> None:
        """Remove all instances in the cluster that are not online.

        Raises:
            MySQLRemoveInstancesNotOnlineRetryError - to retry this method
                if there was an issue removing not online instances
        """
        try:
            cluster_status = self.get_cluster_status()
            if not cluster_status:
                raise MySQLRemoveInstancesNotOnlineRetryError("Unable to retrieve cluster status")

            # If the cluster has no quorum, force quorum using partition of
            # the first online instance
            if cluster_status["defaultreplicaset"]["status"] == "no_quorum":
                logger.warning("Cluster has no quorum")

                online_member_address = [
                    member["address"]
                    for _, member in cluster_status["defaultreplicaset"]["topology"].items()
                    if member["status"] == "online"
                ][0]

                logger.info(f"Forcing quorum using {online_member_address}")
                force_quorum_commands = (
                    f"shell.connect('{self.cluster_admin_user}:{self.cluster_admin_password}@{self.instance_address}')",
                    f"cluster = dba.get_cluster('{self.cluster_name}')",
                    f"cluster.force_quorum_using_partition_of('{self.cluster_admin_user}@{online_member_address}', '{self.cluster_admin_password}')",
                )

                self._run_mysqlsh_script("\n".join(force_quorum_commands))

            self._remove_unreachable_instances()
            self._wait_till_all_members_are_online()
        except MySQLClientError as e:
            # In case of an error (cluster still not stable), raise an error and retry
            logger.warning(
                f"Failed to remove unreachable instances on {self.instance_address} with error {e.message}"
            )
            raise MySQLRemoveInstancesNotOnlineRetryError(e.message)
        except RetryError as e:
            logger.exception(
                "Failed to remove not online instances from the cluster",
                exc_info=e,
            )
            raise MySQLRemoveInstancesNotOnlineError(e.message)

    def create_database(self, database_name: str) -> None:
        """Creates a database.

        Args:
            database_name: Name of database to create

        Raises:
            MySQLCreateDatabaseError if there is an issue creating specified database
        """
        try:
            primary_address = self.get_cluster_primary_address()

            create_database_commands = (
                f"shell.connect('{self.server_config_user}:{self.server_config_password}@{primary_address}')",
                f'session.run_sql("CREATE DATABASE IF NOT EXISTS {database_name};")',
            )

            self._run_mysqlsh_script("\n".join(create_database_commands))
        except MySQLClientError as e:
            logger.exception(f"Failed to create database {database_name}", exc_info=e)
            raise MySQLCreateDatabaseError(e.message)

    def create_user(self, username: str, password: str, label: str, hostname: str = "%") -> None:
        """Creates a new user.

        Args:
            username: The username of the user to create
            password: THe user's password
            label: The label to tag the user with (to be able to delete it later)
            hostname: (Optional) The hostname of the new user to create (% by default)

        Raises:
            MySQLCreateUserError if there is an issue creating specified user
        """
        try:
            primary_address = self.get_cluster_primary_address()

            escaped_user_attributes = json.dumps({"label": label}).replace('"', r"\"")
            create_user_commands = (
                f"shell.connect('{self.server_config_user}:{self.server_config_password}@{primary_address}')",
                f"session.run_sql(\"CREATE USER '{username}'@'{hostname}' IDENTIFIED BY '{password}' ATTRIBUTE '{escaped_user_attributes}';\")",
            )

            self._run_mysqlsh_script("\n".join(create_user_commands))
        except MySQLClientError as e:
            logger.exception(f"Failed to create user {username}@{hostname}", exc_info=e)
            raise MySQLCreateUserError(e.message)

    def escalate_user_privileges(self, username: str, hostname: str = "%") -> None:
        """Escalates the provided user's privileges.

        Args:
            username: The username of the user to escalate privileges for
            hostname: The hostname of the user to escalate privileges for

        Raises:
            MySQLEscalateUserPrivilegesError if there is an error escalating user privileges
        """
        try:
            super_privileges_to_revoke = (
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

            primary_address = self.get_cluster_primary_address()

            escalate_user_privileges_commands = (
                f"shell.connect('{self.server_config_user}:{self.server_config_password}@{primary_address}')",
                f"session.run_sql(\"GRANT ALL ON *.* TO '{username}'@'{hostname}' WITH GRANT OPTION;\")",
                f"session.run_sql(\"REVOKE {', '.join(super_privileges_to_revoke)} ON *.* FROM '{username}'@'{hostname}';\")",
                'session.run_sql("FLUSH PRIVILEGES;")',
            )

            self._run_mysqlsh_script("\n".join(escalate_user_privileges_commands))
        except MySQLClientError as e:
            logger.exception(
                f"Failed to escalate user privileges for {username}@{hostname}", exc_info=e
            )
            raise MySQLEscalateUserPrivilegesError(e.message)

    def delete_users_with_label(self, label_name: str, label_value: str) -> None:
        """Delete users with the provided label.

        Args:
            label_name: The name of the label for users to be deleted
            label_value: The value of the label for users to be deleted

        Raises:
            MySQLDeleteUsersWIthLabelError if there is an error deleting users for the label
        """
        get_label_users = (
            "SELECT CONCAT(user.user, '@', user.host) FROM mysql.user AS user "
            "JOIN information_schema.user_attributes AS attributes"
            " ON (user.user = attributes.user AND user.host = attributes.host) "
            f'WHERE attributes.attribute LIKE \'%"{label_name}": "{label_value}"%\'',
        )

        try:
            output = self._run_mysqlcli_script(
                "; ".join(get_label_users),
                user=self.server_config_user,
                password=self.server_config_password,
            )
            users = [line.strip() for line in output.split("\n") if line.strip()][1:]
            users = [f"'{user.split('@')[0]}'@'{user.split('@')[1]}'" for user in users]

            if len(users) == 0:
                logger.debug(f"There are no users to drop for label {label_name}={label_value}")
                return

            primary_address = self.get_cluster_primary_address()

            # Using server_config_user as we are sure it has drop user grants
            drop_users_command = (
                f"shell.connect('{self.server_config_user}:{self.server_config_password}@{primary_address}')",
                f"session.run_sql(\"DROP USER IF EXISTS {', '.join(users)};\")",
            )
            self._run_mysqlsh_script("\n".join(drop_users_command))
        except MySQLClientError as e:
            logger.exception(
                f"Failed to query and delete users for label {label_name}={label_value}",
                exc_info=e,
            )
            raise MySQLDeleteUsersWithLabelError(e.message)

    def _run_mysqlsh_script(self, script: str, verbose: int = 1) -> str:
        """Execute a MySQL shell script.

        Raises ExecError if the script gets a non-zero return code.

        Args:
            script: mysql-shell python script string
            verbose: mysqlsh verbosity level
        Returns:
            stdout of the script
        """
        self.container.push(path=MYSQLSH_SCRIPT_FILE, source=script)

        # render command with remove file after run
        cmd = [
            "/usr/bin/mysqlsh",
            "--no-wizard",
            "--python",
            f"--verbose={verbose}",
            "-f",
            MYSQLSH_SCRIPT_FILE,
            ";",
            "rm",
            MYSQLSH_SCRIPT_FILE,
        ]

        try:
            process = self.container.exec(cmd)
            stdout, _ = process.wait_output()
            return stdout
        except ExecError as e:
            raise MySQLClientError(e.stderr)

    def _run_mysqlcli_script(self, script: str, password: str = None, user: str = "root") -> str:
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

        try:
            process = self.container.exec(command)
            stdout, _ = process.wait_output()
            return stdout
        except ExecError as e:
            raise MySQLClientError(e.stderr)

    def write_content_to_file(
        self,
        path: str,
        content: str,
        owner: str = MYSQL_SYSTEM_USER,
        group: str = MYSQL_SYSTEM_USER,
        permission: int = 0o640,
    ) -> None:
        """Write content to file.

        Args:
            path: filesystem full path (with filename)
            content: string content to write
            owner: file owner
            group: file group
            permission: file permission
        """
        self.container.push(path, content, permissions=permission, user=owner, group=group)

    def remove_file(self, path: str) -> None:
        """Remove a file from container workload.

        Args:
            path: Full filesystem path to remove
        """
        self.container.remove_path(path)

    def check_if_mysqld_process_stopped(self) -> bool:
        """Checks if the mysqld process is stopped on the container."""
        command = ["ps", "-eo", "comm,stat"]

        try:
            process = self.container.exec(command)
            stdout, _ = process.wait_output()

            for line in stdout.strip().split("\n"):
                [comm, stat] = line.split()

                if comm == "mysqld":
                    return "T" in stat

            return True
        except ExecError as e:
            raise MySQLClientError(e.stderr)
