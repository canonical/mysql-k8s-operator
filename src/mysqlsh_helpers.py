#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper class to manage the MySQL InnoDB cluster lifecycle with MySQL Shell."""

import json
import logging
import re
from typing import List, Tuple

from ops.model import Container
from ops.pebble import ExecError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    stop_after_delay,
    wait_fixed,
    wait_random,
)

logger = logging.getLogger(__name__)

MYSQLD_SOCK_FILE = "/var/run/mysqld/mysqld.sock"
MYSQLSH_SCRIPT_FILE = "/tmp/script.py"
MYSQLD_CONFIG_FILE = "/etc/mysql/conf.d/z-custom.cnf"

UNIT_TEARDOWN_LOCKNAME = "unit-teardown"


class MySQLConfigureInstanceError(Exception):
    """Exception raised when there is an issue configuring a MySQL instance."""

    def __str__(self) -> str:
        """Return a string representation of the exception."""
        return "MySQLConfigureInstanceError"


class MySQLConfigureMySQLUsersError(Exception):
    """Exception raised when creating a user fails."""

    def __str__(self) -> str:
        """Return a string representation of the exception."""
        return "MySQLConfigureMySQLUsersError"


class MySQLServiceNotRunningError(Exception):
    """Exception raised when the MySQL service is not running."""

    pass


class MySQLCreateClusterError(Exception):
    """Exception raised when there is an issue creating an InnoDB cluster."""

    pass


class MySQLAddInstanceToClusterError(Exception):
    """Exception raised when there is an issue add an instance to the MySQL InnoDB cluster."""

    pass


class MySQLInitialiseMySQLDError(Exception):
    """Exception raised when there is an issue initialising an instance."""

    def __str__(self) -> str:
        """Return a string representation of the exception."""
        return "MySQLInitialiseMySQLDError"


class MySQLCreateCustomConfigFileError(Exception):
    """Exception raised when there is an issue creating custom config file."""

    def __str__(self) -> str:
        """Return a string representation of the exception."""
        return "MySQLCreateCustomConfigFile"


class MySQLUpdateAllowListError(Exception):
    """Exception raised when there is an issue updating the allowlist."""

    pass


class MySQLRemoveInstanceRetryError(Exception):
    """Exception raised when there is an issue removing an instance.

    Utilized by tenacity to retry the method.
    """

    pass


class MySQLRemoveInstanceError(Exception):
    """Exception raised when there is an issue removing an instance.

    Exempt from the retry mechanism provided by tenacity.
    """


class MySQLInitializeJujuOperationsTableError(Exception):
    """Exception raised when there is an issue initializing the juju units operations table."""

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
            # set global variables to enable group replication in k8s
            self._set_group_replication_initial_variables()
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
        process = self.container.exec(cmd)
        stdout, _ = process.wait_output()
        return stdout

    def is_instance_configured_for_innodb(self, instance_address: str) -> bool:
        """Confirm if instance is configured for use in an InnoDB cluster.

        Args:
            instance_address: The instance address for which to confirm InnoDB configuration

        Returns:
            Boolean indicating whether the instance is configured for use in an InnoDB cluster
        """
        commands = (
            f"shell.connect('{self.cluster_admin_user}:{self.cluster_admin_password}@{instance_address}')",
            "instance_configured = dba.check_instance_configuration()['status'] == 'ok'",
            'print("INSTANCE_CONFIGURED" if instance_configured else "INSTANCE_NOT_CONFIGURED")',
        )

        try:
            logger.debug(f"Confirming instance {instance_address} configuration for InnoDB")

            output = self._run_mysqlsh_script("\n".join(commands), verbose=0)
            return "INSTANCE_CONFIGURED" in output
        except ExecError:
            # confirmation can fail if the clusteradmin user does not yet exist on the instance
            logger.debug(f"Failed to confirm instance configuration for {instance_address}.")
            return False

    def is_instance_in_cluster(self, instance_address: str) -> bool:
        """Confirm if instance is in the cluster.

        Args:
            instance_address: The instance address for which to confirm InnoDB configuration

        Returns:
            Boolean indicating whether the instance is in the cluster
        """
        commands = (
            f"shell.connect('{self.cluster_admin_user}:{self.cluster_admin_password}@{self.instance_address}')",
            f"cluster = dba.get_cluster('{self.cluster_name}')",
            f"print(cluster.status()['defaultReplicaSet']['topology']['{instance_address}:3306']['status'])",
        )

        try:
            logger.debug(f"Checking if instance {instance_address} is in the cluster")

            output = self._run_mysqlsh_script("\n".join(commands), verbose=0)
            return "ONLINE" in output
        except ExecError:
            # confirmation can fail if the clusteradmin user does not yet exist on the instance
            logger.debug(f"Instance {instance_address} is not yet in the cluster")
            return False

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

    def _get_cluster_status(self) -> dict:
        """Get the cluster status.

        Executes script to retrieve cluster status.
        Won't raise errors.

        Returns:
            Cluster status as a dictionary
        """
        status_commands = (
            f"shell.connect('{self.cluster_admin_user}:{self.cluster_admin_password}@{self.instance_address}')",
            f"cluster = dba.get_cluster('{self.cluster_name}')",
            "print(cluster.status())",
        )

        try:
            output = self._run_mysqlsh_script("\n".join(status_commands), verbose=0)
            output_dict = json.loads(output.lower())
            # pop topology from status due it being potentially too long
            # and containing keys with `:` in it
            output_dict["defaultreplicaset"].pop("topology")
            return output_dict
        except ExecError as e:
            logger.exception(f"Failed to get cluster status for {self.cluster_name}", exc_info=e)

    def _set_group_replication_initial_variables(self) -> None:
        """Set group replication initial variables.

        Necessary for k8s deployments.
        Raises ExecError if the script gets a non-zero return code.
        """
        commands = (
            "INSTALL PLUGIN group_replication SONAME 'group_replication.so';",
            f"SET PERSIST group_replication_local_address='{self.instance_address}:33061';",
            "SET PERSIST group_replication_ip_allowlist='0.0.0.0/0';",
        )

        self._run_mysqlcli_script(
            " ".join(commands), self.cluster_admin_password, self.cluster_admin_user
        )

    def create_custom_config_file(self, report_host: str) -> None:
        """Create custom configuration file.

        Necessary for k8s deployments.
        Raises ExecError if the script gets a non-zero return code.
        """
        content = ("[mysqld]", f"report_host = {report_host}", "")

        try:
            self.container.push(MYSQLD_CONFIG_FILE, source="\n".join(content))
        except Exception:
            raise MySQLCreateCustomConfigFileError()

    def update_allowlist(self, allowlist: str) -> None:
        """Update the allowlist for the cluster.

        Updates the ipAllowlist global variable in the cluster for GR access.
        https://dev.mysql.com/doc/refman/8.0/en/group-replication-ip-address-permissions.html

        Args:
            allowlist: comma separated hosts
        """
        allowlist_commands = f"SET PERSIST group_replication_ip_allowlist='{allowlist}';"

        try:
            self._run_mysqlcli_script(
                allowlist_commands, self.cluster_admin_password, self.cluster_admin_user
            )
        except ExecError:
            logger.debug("Failed to update cluster ipAllowlist")
            raise MySQLUpdateAllowListError()

    def initialize_juju_units_operations_table(self) -> None:
        """Initialize the mysql.juju_units_operations table using the serverconfig user.

        Raises
            MySQLInitializeJujuOperationsTableError if there is an issue
                initializing the juju_units_operations table
        """
        initalise_table_commands = (
            "CREATE TABLE mysql.juju_units_operations (task varchar(20), executor varchar(20), status varchar(20), primary key(task));",
            f"INSERT INTO mysql.juju_units_operations values ('{UNIT_TEARDOWN_LOCKNAME}', '', 'not-started');",
        )

        try:
            logger.debug(
                f"Initializing the juju_units_operations table on {self.instance_address}"
            )

            self._run_mysqlcli_script(
                " ".join(initalise_table_commands),
                user=self.server_config_user,
                password=self.server_config_password,
            )
        except ExecError as e:
            logger.exception(
                f"Failed to initialize mysql.juju_units_operations table with error {e.stderr}",
                exc_info=e,
            )
            raise MySQLInitializeJujuOperationsTableError(e.stderr)

    @retry(
        retry=retry_if_exception_type(MySQLRemoveInstanceRetryError),
        stop=stop_after_attempt(15),
        reraise=True,
        wait=wait_random(min=4, max=30),
    )
    def remove_instance(self, unit_label: str) -> None:
        """Remove instance from the cluster.

        This method is called from each unit being torn down, thus we must obtain
        locks on the cluster primary. There is a retry mechanism for any issues
        obtaining the lock, removing instances/dissolving the cluster, or releasing
        the lock.

        Raises:
            MySQLRemoveInstanceRetryError - to retry this method if there was an issue
                obtaining a lock or removing the instance
            MySQLRemoveInstanceError - if there is an issue releasing
                the lock after the instance is removed from the cluster (avoids retries)

        Args:
            unit_label: The label for this unit's instance (to be torn down)
        """
        try:
            # Get the cluster primary's address to direct lock acquisition request to.
            primary_address = self._get_cluster_primary_address()
            if not primary_address:
                raise MySQLRemoveInstanceRetryError(
                    "Unable to retrieve the cluster primary's address"
                )

            # Attempt to acquire a lock on the primary instance
            acquired_lock = self._acquire_lock(primary_address, unit_label, UNIT_TEARDOWN_LOCKNAME)
            if not acquired_lock:
                raise MySQLRemoveInstanceRetryError("Did not acquire lock to remove unit")

            # Get remaining cluster member addresses before calling mysqlsh.remove_instance()
            remaining_cluster_member_addresses, valid = self._get_cluster_member_addresses(
                exclude_unit_labels=[unit_label]
            )
            if not valid:
                raise MySQLRemoveInstanceRetryError("Unable to retrieve cluster member addresses")

            # Remove instance from cluster, or dissolve cluster if no other members remain
            logger.debug(
                f"Removing instance {self.instance_address} from cluster {self.cluster_name}"
            )
            remove_instance_options = {
                "password": self.cluster_admin_password,
                "force": "true",
            }
            dissolve_cluster_options = {
                "force": "true",
            }
            remove_instance_commands = (
                f"shell.connect('{self.cluster_admin_user}:{self.cluster_admin_password}@{self.instance_address}')",
                f"cluster = dba.get_cluster('{self.cluster_name}')",
                "number_cluster_members = len(cluster.status()['defaultReplicaSet']['topology'])",
                f"cluster.remove_instance('{self.cluster_admin_user}@{self.instance_address}', {json.dumps(remove_instance_options)}) if number_cluster_members > 1 else cluster.dissolve({json.dumps(dissolve_cluster_options)})",
            )
            self._run_mysqlsh_script("\n".join(remove_instance_commands))
        except ExecError as e:
            # In case of an error, raise an error and retry
            logger.warning(
                f"Failed to acquire lock and remove instance {self.instance_address} with error {e.stderr}",
                exc_info=e,
            )
            raise MySQLRemoveInstanceRetryError(e.stderr)

        # There is no need to release the lock if cluster was dissolved
        if not remaining_cluster_member_addresses:
            return

        # The below code should not result in retries of this method since the
        # instance would already be removed from the cluster.
        try:
            # Retrieve the cluster primary's address again (in case the old primary is scaled down)
            # Release the lock by making a request to this primary member's address
            primary_address = self._get_cluster_primary_address(
                connect_instance_address=remaining_cluster_member_addresses[0]
            )
            if not primary_address:
                raise MySQLRemoveInstanceError(
                    "Unable to retrieve the address of the cluster primary"
                )

            self._release_lock(primary_address, unit_label, UNIT_TEARDOWN_LOCKNAME)
        except ExecError as e:
            # Raise an error that does not lead to a retry of this method
            logger.exception(
                f"Failed to release lock on {unit_label} with error {e.stderr}", exc_info=e
            )
            raise MySQLRemoveInstanceError(e.stderr)

    def _acquire_lock(self, primary_address: str, unit_label: str, lock_name: str) -> bool:
        """Attempts to acquire a lock by using the mysql.juju_units_operations table.

        Note that there must exist the appropriate rows in the table, created in the
        initialize_juju_units_operations_table() method.

        Args:
            primary_address: The address of the cluster's primary
            unit_label: The label of the unit for which to obtain the lock
            lock_name: The name of the lock to obtain

        Raises:
            ExecError if there's an issue acquiring the lock

        Returns:
            Boolean indicating whether the lock was obtained
        """
        logger.debug(
            f"Attempting to acquire lock {lock_name} on {primary_address} for unit {unit_label}"
        )

        acquire_lock_commands = (
            f"shell.connect('{self.cluster_admin_user}:{self.cluster_admin_password}@{primary_address}')",
            f"session.run_sql(\"UPDATE mysql.juju_units_operations SET executor='{unit_label}', status='in-progress' WHERE task='{lock_name}' AND executor='';\")",
            f"acquired_lock = session.run_sql(\"SELECT count(*) FROM mysql.juju_units_operations WHERE task='{lock_name}' AND executor='{unit_label}';\").fetch_one()[0]",
            "print(f'<ACQUIRED_LOCK>{acquired_lock}</ACQUIRED_LOCK>')",
        )

        output = self._run_mysqlsh_script("\n".join(acquire_lock_commands))
        matches = re.search(r"<ACQUIRED_LOCK>(\d)</ACQUIRED_LOCK>", output)
        if not matches:
            return False

        return bool(int(matches.group(1)))

    def _release_lock(self, primary_address: str, unit_label: str, lock_name: str) -> None:
        """Releases a lock in the mysql.juju_units_operations table.

        Note that there must exist the appropriate rows in the table, created in the
        initialize_juju_units_operations_table() method.

        Args:
            primary_address: The address of the cluster's primary
            unit_label: The label of the unit to release the lock for
            lock_name: The name of the lock to release

        Raises:
            ExecError if there's an issue releasing the lock
        """
        logger.debug(f"Releasing lock {lock_name} on {primary_address} for unit {unit_label}")

        release_lock_commands = (
            f"shell.connect('{self.cluster_admin_user}:{self.cluster_admin_password}@{primary_address}')",
            f"session.run_sql(\"UPDATE mysql.juju_units_operations SET executor='', status='not-started' WHERE task='{lock_name}' AND executor='{unit_label}';\")",
        )
        self._run_mysqlsh_script("\n".join(release_lock_commands))

    def _get_cluster_member_addresses(self, exclude_unit_labels: List = []) -> Tuple[List, bool]:
        """Get the addresses of the cluster's members.

        Keyword args:
            exclude_unit_labels: (Optional) unit labels to exclude when retrieving cluster members

        Raises:
            ExecError if there is an issue getting cluster
                members' addresses

        Returns:
            ([member_addresses], valid): a list of member addresses and
                whether the method's execution was valid
        """
        logger.debug(f"Getting cluster member addresses, excluding units {exclude_unit_labels}")

        get_cluster_members_commands = (
            f"shell.connect('{self.cluster_admin_user}:{self.cluster_admin_password}@{self.instance_address}')",
            f"cluster = dba.get_cluster('{self.cluster_name}')",
            f"member_addresses = ','.join([member['address'] for label, member in cluster.status()['defaultReplicaSet']['topology'].items() if label not in {exclude_unit_labels}])",
            "print(f'<MEMBER_ADDRESSES>{member_addresses}</MEMBER_ADDRESSES>')",
        )

        output = self._run_mysqlsh_script("\n".join(get_cluster_members_commands))
        matches = re.search(r"<MEMBER_ADDRESSES>(.*)</MEMBER_ADDRESSES>", output)

        if not matches:
            return ([], False)

        # Filter out any empty values (in case there are no members)
        member_addresses = [
            member_address for member_address in matches.group(1).split(",") if member_address
        ]

        return (member_addresses, "<MEMBER_ADDRESSES>" in output)

    def _get_cluster_primary_address(self, connect_instance_address: str = None) -> str:
        """Get the cluster primary's address.

        Keyword args:
            connect_instance_address: The address for the cluster primary
                (default to this instance's address)

        Raises:
            ExecError if there is an issue retrieving the
                cluster primary's address

        Returns:
            The address of the cluster's primary
        """
        logger.debug(f"Getting cluster primary member's address from {connect_instance_address}")

        if not connect_instance_address:
            connect_instance_address = self.instance_address

        get_cluster_primary_commands = (
            f"shell.connect('{self.cluster_admin_user}:{self.cluster_admin_password}@{connect_instance_address}')",
            f"cluster = dba.get_cluster('{self.cluster_name}')",
            "primary_address = sorted([cluster_member['address'] for cluster_member in cluster.status()['defaultReplicaSet']['topology'].values() if cluster_member['mode'] == 'R/W'])[0]",
            "print(f'<PRIMARY_ADDRESS>{primary_address}</PRIMARY_ADDRESS>')",
        )

        output = self._run_mysqlsh_script("\n".join(get_cluster_primary_commands))
        matches = re.search(r"<PRIMARY_ADDRESS>(.+)</PRIMARY_ADDRESS>", output)

        if not matches:
            return None

        return matches.group(1)
