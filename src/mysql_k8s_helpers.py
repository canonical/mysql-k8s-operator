#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper class to manage the MySQL InnoDB cluster lifecycle with MySQL Shell."""

import json
import logging
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import jinja2
from charms.mysql.v0.mysql import (
    Error,
    MySQLBase,
    MySQLClientError,
    MySQLExecError,
    MySQLGetClusterEndpointsError,
    MySQLServiceNotRunningError,
    MySQLStartMySQLDError,
    MySQLStopMySQLDError,
)
from ops.model import Container
from ops.pebble import ChangeError, ExecError, PathError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    stop_after_delay,
    wait_fixed,
)

from constants import (
    CHARMED_MYSQL_XBCLOUD_LOCATION,
    CHARMED_MYSQL_XBSTREAM_LOCATION,
    CHARMED_MYSQL_XTRABACKUP_LOCATION,
    CONTAINER_NAME,
    LOG_ROTATE_CONFIG_FILE,
    MYSQL_CLI_LOCATION,
    MYSQL_DATA_DIR,
    MYSQL_SYSTEM_GROUP,
    MYSQL_SYSTEM_USER,
    MYSQLD_DEFAULTS_CONFIG_FILE,
    MYSQLD_LOCATION,
    MYSQLD_SAFE_SERVICE,
    MYSQLD_SOCK_FILE,
    MYSQLSH_LOCATION,
    MYSQLSH_SCRIPT_FILE,
    ROOT_SYSTEM_USER,
    XTRABACKUP_PLUGIN_DIR,
)
from k8s_helpers import KubernetesClientError, KubernetesHelpers
from utils import any_memory_to_bytes

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from charm import MySQLOperatorCharm


class MySQLInitialiseMySQLDError(Error):
    """Exception raised when there is an issue initialising an instance."""


class MySQLCreateCustomConfigFileError(Error):
    """Exception raised when there is an issue creating custom config file."""


class MySQLCreateDatabaseError(Error):
    """Exception raised when there is an issue creating a database."""


class MySQLCreateUserError(Error):
    """Exception raised when there is an issue creating a user."""


class MySQLEscalateUserPrivilegesError(Error):
    """Exception raised when there is an issue escalating user privileges."""


class MySQLDeleteUsersWithLabelError(Error):
    """Exception raised when there is an issue deleting users with a label."""


class MySQLWaitUntilUnitRemovedFromClusterError(Error):
    """Exception raised when there is an issue checking if a unit is removed from the cluster."""


class MySQLExecuteBackupCommandsError(Error):
    """Exception raised when there is an error executing the backup commands.

    The backup commands are executed in the workload container using the pebble API.
    """


class MySQLRetrieveBackupWithXBCloudError(Error):
    """Exception raised when there is an error retrieving a backup from S3 with xbcloud."""


class MySQLPrepareBackupForRestoreError(Error):
    """Exception raised when there is an error preparing a backup for restore."""


class MySQLEmptyDataDirectoryError(Error):
    """Exception raised when there is an error emptying the mysql data directory."""


class MySQLRestoreBackupError(Error):
    """Exception raised when there is an error restoring a backup."""


class MySQLDeleteTempBackupDirectoryError(Error):
    """Exception raised when there is an error deleting the temp backup directory."""


class MySQLDeleteTempRestoreDirectory(Error):
    """Exception raised when there is an error deleting the temp restore directory."""


class MySQL(MySQLBase):
    """Class to encapsulate all operations related to the MySQL instance and cluster.

    This class handles the configuration of MySQL instances, and also the
    creation and configuration of MySQL InnoDB clusters via Group Replication.
    """

    def __init__(
        self,
        instance_address: str,
        cluster_name: str,
        cluster_set_name: str,
        root_password: str,
        server_config_user: str,
        server_config_password: str,
        cluster_admin_user: str,
        cluster_admin_password: str,
        monitoring_user: str,
        monitoring_password: str,
        backups_user: str,
        backups_password: str,
        container: Container,
        k8s_helper: KubernetesHelpers,
        charm: "MySQLOperatorCharm",
    ):
        """Initialize the MySQL class.

        Args:
            instance_address: address of the targeted instance
            cluster_name: cluster name
            cluster_set_name: cluster set name
            root_password: password for the 'root' user
            server_config_user: user name for the server config user
            server_config_password: password for the server config user
            cluster_admin_user: user name for the cluster admin user
            cluster_admin_password: password for the cluster admin user
            monitoring_user: user name for the monitoring user
            monitoring_password: password for the monitoring user
            backups_user: user name for the backups user
            backups_password: password for the backups user
            container: workload container object
            k8s_helper: KubernetesHelpers object
            charm: charm object
        """
        super().__init__(
            instance_address=instance_address,
            cluster_name=cluster_name,
            cluster_set_name=cluster_set_name,
            root_password=root_password,
            server_config_user=server_config_user,
            server_config_password=server_config_password,
            cluster_admin_user=cluster_admin_user,
            cluster_admin_password=cluster_admin_password,
            monitoring_user=monitoring_user,
            monitoring_password=monitoring_password,
            backups_user=backups_user,
            backups_password=backups_password,
        )
        self.container = container
        self.k8s_helper = k8s_helper
        self.charm = charm

    def fix_data_dir(self, container: Container) -> None:
        """Ensure the data directory for mysql is writable for the "mysql" user.

        Until the ability to set fsGroup and fsGroupChangePolicy via Pod securityContext
        is available we fix permissions incorrectly with chown.
        """
        paths = container.list_files(MYSQL_DATA_DIR, itself=True)
        assert len(paths) == 1, "list_files doesn't return only directory itself"
        logger.debug(f"Data directory ownership: {paths[0].user}:{paths[0].group}")
        if paths[0].user != MYSQL_SYSTEM_USER or paths[0].group != MYSQL_SYSTEM_GROUP:
            logger.debug(f"Changing ownership to {MYSQL_SYSTEM_USER}:{MYSQL_SYSTEM_GROUP}")
            try:
                container.exec(
                    ["chown", "-R", f"{MYSQL_SYSTEM_USER}:{MYSQL_SYSTEM_GROUP}", MYSQL_DATA_DIR]
                )
            except ExecError as e:
                logger.error(f"Exited with code {e.exit_code}. Stderr:\n{e.stderr}")
                raise MySQLInitialiseMySQLDError(e.stderr or "")

    @retry(reraise=True, stop=stop_after_delay(30), wait=wait_fixed(5))
    def initialise_mysqld(self) -> None:
        """Execute instance first run.

        Initialise mysql data directory and create blank password root@localhost user.
        Raises MySQLInitialiseMySQLDError if the instance bootstrap fails.
        """
        bootstrap_command = [MYSQLD_LOCATION, "--initialize-insecure", "-u", MYSQL_SYSTEM_USER]

        try:
            process = self.container.exec(
                command=bootstrap_command,
                user=MYSQL_SYSTEM_USER,
                group=MYSQL_SYSTEM_GROUP,
            )
            process.wait()
        except (ExecError, ChangeError, PathError, TimeoutError):
            logger.exception("Failed to initialise MySQL data directory")
            self.reset_data_dir()
            raise MySQLInitialiseMySQLDError

    @retry(reraise=True, stop=stop_after_delay(120), wait=wait_fixed(2))
    def wait_until_mysql_connection(self, check_port: bool = True) -> None:
        """Wait until a connection to MySQL daemon is possible.

        Retry every 2 seconds for 120 seconds if there is an issue obtaining a connection.
        """
        if not self.container.exists(MYSQLD_SOCK_FILE):
            raise MySQLServiceNotRunningError

        try:
            if check_port and not self.check_mysqlsh_connection():
                raise MySQLServiceNotRunningError("Connection with mysqlsh not possible")
        except MySQLClientError:
            raise MySQLServiceNotRunningError

        logger.debug("MySQL connection possible")

    def setup_logrotate_config(self) -> None:
        """Set up logrotate config in the workload container."""
        logger.debug("Creating the logrotate config file")

        with open("templates/logrotate.j2", "r") as file:
            template = jinja2.Template(file.read())

        rendered = template.render(
            system_user=MYSQL_SYSTEM_USER,
            system_group=MYSQL_SYSTEM_GROUP,
        )

        logger.debug("Writing the logrotate config file to the workload container")
        self.write_content_to_file(
            LOG_ROTATE_CONFIG_FILE,
            rendered,
            owner=ROOT_SYSTEM_USER,
            group=ROOT_SYSTEM_USER,
        )

    def execute_backup_commands(
        self,
        s3_directory: str,
        s3_parameters: Dict[str, str],
    ) -> Tuple[str, str]:
        """Executes commands to create a backup."""
        return super().execute_backup_commands(
            s3_directory,
            s3_parameters,
            CHARMED_MYSQL_XTRABACKUP_LOCATION,
            CHARMED_MYSQL_XBCLOUD_LOCATION,
            XTRABACKUP_PLUGIN_DIR,
            MYSQLD_SOCK_FILE,
            MYSQL_DATA_DIR,
            MYSQLD_DEFAULTS_CONFIG_FILE,
            user=MYSQL_SYSTEM_USER,
            group=MYSQL_SYSTEM_GROUP,
        )

    def delete_temp_backup_directory(self, from_directory: str = MYSQL_DATA_DIR) -> None:
        """Delete the temp backup directory in the data directory."""
        super().delete_temp_backup_directory(
            from_directory,
            user=MYSQL_SYSTEM_USER,
            group=MYSQL_SYSTEM_GROUP,
        )

    def retrieve_backup_with_xbcloud(
        self,
        backup_id: str,
        s3_parameters: Dict[str, str],
    ) -> Tuple[str, str, str]:
        """Retrieve the specified backup from S3.

        The backup is retrieved using xbcloud and stored in a temp dir in the
        mysql container.
        """
        return super().retrieve_backup_with_xbcloud(
            backup_id,
            s3_parameters,
            MYSQL_DATA_DIR,
            CHARMED_MYSQL_XBCLOUD_LOCATION,
            CHARMED_MYSQL_XBSTREAM_LOCATION,
            user=MYSQL_SYSTEM_USER,
            group=MYSQL_SYSTEM_GROUP,
        )

    def prepare_backup_for_restore(self, backup_location: str) -> Tuple[str, str]:
        """Prepare the backup in the provided dir for restore."""
        return super().prepare_backup_for_restore(
            backup_location,
            CHARMED_MYSQL_XTRABACKUP_LOCATION,
            XTRABACKUP_PLUGIN_DIR,
            user=MYSQL_SYSTEM_USER,
            group=MYSQL_SYSTEM_GROUP,
        )

    def empty_data_files(self) -> None:
        """Empty the mysql data directory in preparation of backup restore."""
        super().empty_data_files(
            MYSQL_DATA_DIR,
            user=MYSQL_SYSTEM_USER,
            group=MYSQL_SYSTEM_GROUP,
        )

    def restore_backup(self, backup_location: str) -> Tuple[str, str]:
        """Restore the provided prepared backup."""
        return super().restore_backup(
            backup_location,
            CHARMED_MYSQL_XTRABACKUP_LOCATION,
            MYSQLD_DEFAULTS_CONFIG_FILE,
            MYSQL_DATA_DIR,
            XTRABACKUP_PLUGIN_DIR,
            user=MYSQL_SYSTEM_USER,
            group=MYSQL_SYSTEM_GROUP,
        )

    def delete_temp_restore_directory(self) -> None:
        """Delete the temp restore directory from the mysql data directory."""
        super().delete_temp_restore_directory(
            MYSQL_DATA_DIR,
            user=MYSQL_SYSTEM_USER,
            group=MYSQL_SYSTEM_GROUP,
        )

    @retry(
        retry=retry_if_exception_type(MySQLWaitUntilUnitRemovedFromClusterError),
        stop=stop_after_attempt(10),
        wait=wait_fixed(60),
    )
    def _wait_until_unit_removed_from_cluster(self, unit_address: str) -> None:
        """Waits until the provided unit is no longer in the cluster.

        Retries every minute for 10 minutes if the unit is still present in the cluster.

        Args:
            unit_address: The address of the unit that was removed
                and needs to be waited until
        """
        cluster_status = self.get_cluster_status()
        if not cluster_status:
            raise MySQLWaitUntilUnitRemovedFromClusterError("Unable to get cluster status")

        members_in_cluster = [
            member["address"]
            for member in cluster_status["defaultreplicaset"]["topology"].values()
        ]

        if unit_address in members_in_cluster:
            raise MySQLWaitUntilUnitRemovedFromClusterError("Remove member still in cluster")

    def create_database(self, database_name: str) -> None:
        """Creates a database.

        Args:
            database_name: Name of database to create

        Raises:
            MySQLCreateDatabaseError if there is an issue creating specified database
        """
        try:
            create_database_commands = (
                (
                    f"shell.connect_to_primary('{self.server_config_user}:"
                    f"{self.server_config_password}@{self.instance_address}')"
                ),
                f'session.run_sql("CREATE DATABASE IF NOT EXISTS `{database_name}`;")',
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
            escaped_user_attributes = json.dumps({"label": label}).replace('"', r"\"")
            create_user_commands = (
                (
                    f"shell.connect_to_primary('{self.server_config_user}:"
                    f"{self.server_config_password}@{self.instance_address}')"
                ),
                (
                    f'session.run_sql("CREATE USER `{username}`@`{hostname}` IDENTIFIED'
                    f" BY '{password}' ATTRIBUTE '{escaped_user_attributes}';\")"
                ),
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

            escalate_user_privileges_commands = (
                (
                    f"shell.connect_to_primary('{self.server_config_user}:"
                    f"{self.server_config_password}@{self.instance_address}')"
                ),
                f'session.run_sql("GRANT ALL ON *.* TO `{username}`@`{hostname}` WITH GRANT OPTION;")',
                f"session.run_sql(\"REVOKE {', '.join(super_privileges_to_revoke)} ON *.* FROM `{username}`@`{hostname}`;\")",
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

            # Using server_config_user as we are sure it has drop user grants
            drop_users_command = (
                (
                    f"shell.connect_to_primary('{self.server_config_user}:"
                    f"{self.server_config_password}@{self.instance_address}')"
                ),
                f"session.run_sql(\"DROP USER IF EXISTS {', '.join(users)};\")",
            )
            self._run_mysqlsh_script("\n".join(drop_users_command))
        except MySQLClientError as e:
            logger.exception(
                f"Failed to query and delete users for label {label_name}={label_value}",
                exc_info=e,
            )
            raise MySQLDeleteUsersWithLabelError(e.message)

    def is_mysqld_running(self) -> bool:
        """Returns whether server is connectable and mysqld is running."""
        return self.is_server_connectable() and self.container.exists(MYSQLD_SOCK_FILE)

    def is_server_connectable(self) -> bool:
        """Returns whether the server is connectable."""
        return self.container.can_connect()

    def stop_mysqld(self) -> None:
        """Stops the mysqld process."""
        try:
            self.container.stop(MYSQLD_SAFE_SERVICE)
        except ChangeError:
            error_message = f"Failed to stop service {MYSQLD_SAFE_SERVICE}"
            logger.exception(error_message)
            raise MySQLStopMySQLDError(error_message)

    def start_mysqld(self) -> None:
        """Starts the mysqld process."""
        try:
            self.container.start(MYSQLD_SAFE_SERVICE)
            self.wait_until_mysql_connection()
        except (
            ChangeError,
            MySQLServiceNotRunningError,
        ):
            error_message = f"Failed to start service {MYSQLD_SAFE_SERVICE}"
            logger.exception(error_message)
            raise MySQLStartMySQLDError(error_message)

    def restart_mysql_exporter(self) -> None:
        """Restarts the mysqld exporter service in pebble."""
        self.charm._reconcile_pebble_layer(self.container)

    def _execute_commands(
        self,
        commands: List[str],
        bash: bool = False,
        user: Optional[str] = None,
        group: Optional[str] = None,
        env_extra: Optional[Dict] = None,
        timeout: Optional[float] = None,
    ) -> Tuple[str, str]:
        """Execute commands on the server where MySQL is running."""
        try:
            if bash:
                commands = ["bash", "-c", "set -o pipefail; " + " ".join(commands)]

            process = self.container.exec(
                commands,
                user=user,
                group=group,
                environment=env_extra,
                timeout=timeout,
            )
            stdout, stderr = process.wait_output()
            return (stdout, stderr or "")
        except ExecError as e:
            logger.debug(f"Failed command: {commands=}, {user=}, {group=}")
            raise MySQLExecError(e.stderr)

    def _run_mysqlsh_script(
        self, script: str, verbose: int = 1, timeout: Optional[int] = None
    ) -> str:
        """Execute a MySQL shell script.

        Raises ExecError if the script gets a non-zero return code.

        Args:
            script: mysql-shell python script string
            verbose: mysqlsh verbosity level

        Returns:
            stdout of the script
        """
        # TODO: remove timeout from _run_mysqlsh_script contract/signature in the mysql lib
        self.container.push(path=MYSQLSH_SCRIPT_FILE, source=script)

        # render command with remove file after run
        cmd = [
            MYSQLSH_LOCATION,
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
            process = self.container.exec(cmd, timeout=timeout)
            stdout, _ = process.wait_output()
            return stdout
        except ExecError as e:
            raise MySQLClientError(e.stderr)
        except ChangeError as e:
            raise MySQLClientError(e)

    def _run_mysqlcli_script(
        self,
        script: str,
        user: str = "root",
        password: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> str:
        """Execute a MySQL CLI script.

        Execute SQL script as instance root user.
        Raises ExecError if the script gets a non-zero return code.

        Args:
            script: raw SQL script string
            password: root password to use for the script when needed
            user: user to run the script
            timeout: a timeout to execute the mysqlcli script
        """
        command = [
            MYSQL_CLI_LOCATION,
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
            process = self.container.exec(command, timeout=timeout)
            stdout, _ = process.wait_output()
            return stdout
        except ExecError as e:
            raise MySQLClientError(e.stderr)
        except ChangeError as e:
            raise MySQLClientError(e)

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

    def read_file_content(self, path: str) -> Optional[str]:
        """Read file content.

        Args:
            path: filesystem full path (with filename)

        Returns:
            file content
        """
        if not self.container.exists(path):
            return None

        content = self.container.pull(path, encoding="utf8")
        return content.read()

    def remove_file(self, path: str) -> None:
        """Remove a file (if it exists) from container workload.

        Args:
            path: Full filesystem path to remove
        """
        if self.container.exists(path):
            self.container.remove_path(path)

    def reset_data_dir(self) -> None:
        """Remove all files from the data directory."""
        content = self.container.list_files(MYSQL_DATA_DIR)
        content_set = {item.name for item in content}
        logger.debug("Resetting MySQL data directory.")
        for item in content_set:
            self.container.remove_path(f"{MYSQL_DATA_DIR}/{item}", recursive=True)

    def check_if_mysqld_process_stopped(self) -> bool:
        """Checks if the mysqld process is stopped on the container."""
        command = ["ps", "-eo", "comm,stat"]

        try:
            process = self.container.exec(command)
            stdout, _ = process.wait_output()

            for line in stdout.strip().split("\n"):
                [comm, stat] = line.split()

                if comm == MYSQLD_SAFE_SERVICE:
                    return "T" in stat

            return True
        except ExecError as e:
            raise MySQLClientError(e.stderr)

    def get_available_memory(self) -> int:
        """Get available memory for the container in bytes."""
        allocable_memory = self.k8s_helper.get_node_allocable_memory()
        container_limits = self.k8s_helper.get_resources_limits(CONTAINER_NAME)
        if "memory" in container_limits:
            memory_str = container_limits["memory"]
            constrained_memory = any_memory_to_bytes(memory_str)
            if constrained_memory < allocable_memory:
                logger.debug(f"Memory constrained to {memory_str} from resource limit")
                return constrained_memory

        logger.debug("Memory constrained by node allocable memory")
        return allocable_memory

    def is_data_dir_initialised(self) -> bool:
        """Check if data dir is initialised.

        Returns:
            A bool for an initialised and integral data dir.
        """
        try:
            content = self.container.list_files(MYSQL_DATA_DIR)
            content_set = {item.name for item in content}

            # minimal expected content for an integral mysqld data-dir
            expected_content = {
                "#innodb_redo",
                "#innodb_temp",
                "auto.cnf",
                "ca-key.pem",
                "ca.pem",
                "client-cert.pem",
                "client-key.pem",
                "ib_buffer_pool",
                "mysql",
                "mysql.ibd",
                "performance_schema",
                "private_key.pem",
                "public_key.pem",
                "server-cert.pem",
                "server-key.pem",
                "sys",
                "undo_001",
                "undo_002",
            }

            return expected_content <= content_set
        except ExecError:
            return False

    def update_endpoints(self) -> None:
        """Updates pod labels to reflect role of the unit."""
        logger.debug("Updating pod labels")
        try:
            rw_endpoints, ro_endpoints, offline = self.get_cluster_endpoints(get_ips=False)

            for endpoints, label in (
                (rw_endpoints, "primary"),
                (ro_endpoints, "replicas"),
                (offline, "offline"),
            ):
                for pod in (p.split(".")[0] for p in endpoints.split(",")):
                    if pod:
                        self.k8s_helper.label_pod(label, pod)
        except MySQLGetClusterEndpointsError:
            logger.exception("Failed to get cluster endpoints")
        except KubernetesClientError:
            logger.exception("Can't update pod labels")

    def set_cluster_primary(self, new_primary_address: str) -> None:
        """Set the cluster primary and update pod labels."""
        super().set_cluster_primary(new_primary_address)
        self.update_endpoints()

    def fetch_error_log(self) -> Optional[str]:
        """Fetch the MySQL error log."""
        return self.read_file_content("/var/log/mysql/error.log")
