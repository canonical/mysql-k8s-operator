# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from unittest.mock import MagicMock, patch

import tenacity
from charms.mysql.v0.mysql import MySQLClientError, MySQLConfigureMySQLUsersError
from ops.pebble import ExecError

from mysql_k8s_helpers import (
    MYSQLD_SOCK_FILE,
    MYSQLSH_SCRIPT_FILE,
    MySQL,
    MySQLCreateDatabaseError,
    MySQLCreateUserError,
    MySQLDeleteUsersWithLabelError,
    MySQLEscalateUserPrivilegesError,
    MySQLInitialiseMySQLDError,
    MySQLWaitUntilUnitRemovedFromClusterError,
)

GET_CLUSTER_STATUS_RETURN = {
    "defaultreplicaset": {
        "status": "no_quorum",
        "topology": {
            "mysql-0": {
                "status": "online",
                "address": "mysql-0.mysql-endpoints",
            },
            "mysql-2": {
                "status": "unreachable",
                "address": "mysql-2.mysql-endpoints",
            },
            "mysql-1": {
                "status": "(missing)",
                "address": "mysql-1.mysql-endpoints",
            },
        },
    },
}


class TestMySQL(unittest.TestCase):
    def setUp(self):
        self.mysql = MySQL(
            "127.0.0.1",
            "test_cluster",
            "test_cluster_set",
            "password",
            "serverconfig",
            "serverconfigpassword",
            "clusteradmin",
            "clusteradminpassword",
            "monitoring",
            "monitoringpassword",
            "backups",
            "backupspassword",
            None,
            None,
        )

    @patch("ops.pebble.ExecProcess")
    @patch("ops.model.Container")
    def test_initialise_mysqld(self, _container, _process):
        """Test a successful execution of bootstrap_instance."""
        _container.exec.return_value = _process
        self.mysql.container = _container

        self.mysql.initialise_mysqld()

        _container.exec.assert_called_once_with(
            command=["mysqld", "--initialize-insecure", "-u", "mysql"],
            user="mysql",
            group="mysql",
        )

        _process.wait_output.assert_called_once()

    @patch("ops.model.Container")
    def test_initialise_mysqld_exception(self, _container):
        """Test a failing execution of bootstrap_instance."""
        _container.exec.side_effect = ExecError(
            command=["mysqld"], exit_code=1, stdout=b"", stderr=b"Error"
        )
        self.mysql.container = _container

        with self.assertRaises(MySQLInitialiseMySQLDError):
            self.mysql.initialise_mysqld()

    @patch("mysql_k8s_helpers.MySQL._run_mysqlcli_script")
    def test_configure_mysql_users(self, _run_mysqlcli_script):
        """Test failed to configuring the MySQL users."""
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

        _expected_configure_user_commands = "; ".join(
            (
                "CREATE USER 'root'@'%' IDENTIFIED BY 'password'",
                "GRANT ALL ON *.* TO 'root'@'%' WITH GRANT OPTION",
                "CREATE USER 'serverconfig'@'%' IDENTIFIED BY 'serverconfigpassword'",
                "GRANT ALL ON *.* TO 'serverconfig'@'%' WITH GRANT OPTION",
                "CREATE USER 'monitoring'@'%' IDENTIFIED BY 'monitoringpassword' WITH MAX_USER_CONNECTIONS 3",
                "GRANT SYSTEM_USER, SELECT, PROCESS, SUPER, REPLICATION CLIENT, RELOAD ON *.* TO 'monitoring'@'%'",
                "CREATE USER 'backups'@'%' IDENTIFIED BY 'backupspassword'",
                "GRANT CONNECTION_ADMIN, BACKUP_ADMIN, PROCESS, RELOAD, LOCK TABLES, REPLICATION CLIENT ON *.* TO 'backups'@'%'",
                "GRANT SELECT ON performance_schema.log_status TO 'backups'@'%'",
                "GRANT SELECT ON performance_schema.keyring_component_status TO 'backups'@'%'",
                "GRANT SELECT ON performance_schema.replication_group_members TO 'backups'@'%'",
                "UPDATE mysql.user SET authentication_string=null WHERE User='root' and Host='localhost'",
                "ALTER USER 'root'@'localhost' IDENTIFIED BY 'password'",
                f"REVOKE {', '.join(privileges_to_revoke)} ON *.* FROM 'root'@'%'",
                f"REVOKE {', '.join(privileges_to_revoke)} ON *.* FROM 'root'@'localhost'",
                "FLUSH PRIVILEGES",
            )
        )

        self.mysql.configure_mysql_users()

        _run_mysqlcli_script.assert_called_once_with(_expected_configure_user_commands)

    @patch("mysql_k8s_helpers.MySQL._run_mysqlcli_script")
    def test_configure_mysql_users_exception(self, _run_mysqlcli_script):
        """Test exceptions trying to configuring the MySQL users."""
        _run_mysqlcli_script.side_effect = MySQLClientError("Error running mysql")

        with self.assertRaises(MySQLConfigureMySQLUsersError):
            self.mysql.configure_mysql_users()

    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    def test_create_database(self, _run_mysqlsh_script):
        """Test successful execution of create_database."""
        _expected_create_database_commands = (
            "shell.connect_to_primary('serverconfig:serverconfigpassword@127.0.0.1')",
            'session.run_sql("CREATE DATABASE IF NOT EXISTS `test_database`;")',
        )

        self.mysql.create_database("test_database")

        _run_mysqlsh_script.assert_called_once_with("\n".join(_expected_create_database_commands))

    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    def test_create_database_exception(self, _run_mysqlsh_script):
        """Test exception while executing create_database."""
        _run_mysqlsh_script.side_effect = MySQLClientError("Error creating database")

        with self.assertRaises(MySQLCreateDatabaseError):
            self.mysql.create_database("test_database")

    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    def test_create_user(self, _run_mysqlsh_script):
        """Test successful execution of create_user."""
        _escaped_attributes = json.dumps({"label": "test_label"}).replace('"', r"\"")
        _expected_create_user_commands = (
            "shell.connect_to_primary('serverconfig:serverconfigpassword@127.0.0.1')",
            f"session.run_sql(\"CREATE USER `test_user`@`%` IDENTIFIED BY 'test_password' ATTRIBUTE '{_escaped_attributes}';\")",
        )

        self.mysql.create_user("test_user", "test_password", "test_label")

        _run_mysqlsh_script.assert_called_once_with("\n".join(_expected_create_user_commands))

    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    def test_create_user_exception(self, _run_mysqlsh_script):
        """Test exception while executing create_user."""
        _run_mysqlsh_script.side_effect = MySQLClientError("Error creating user")

        with self.assertRaises(MySQLCreateUserError):
            self.mysql.create_user("test_user", "test_password", "test_label")

    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    def test_escalate_user_privileges(self, _run_mysqlsh_script):
        """Test successful execution of escalate_user_privileges."""
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

        _expected_escalate_user_privileges_commands = (
            "shell.connect_to_primary('serverconfig:serverconfigpassword@127.0.0.1')",
            'session.run_sql("GRANT ALL ON *.* TO `test_user`@`%` WITH GRANT OPTION;")',
            f"session.run_sql(\"REVOKE {', '.join(super_privileges_to_revoke)} ON *.* FROM `test_user`@`%`;\")",
            'session.run_sql("FLUSH PRIVILEGES;")',
        )

        self.mysql.escalate_user_privileges("test_user")

        _run_mysqlsh_script.assert_called_once_with(
            "\n".join(_expected_escalate_user_privileges_commands)
        )

    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    def test_escalate_user_privileges_exception(self, _run_mysqlsh_script):
        """Test exception while executing escalate_user_privileges."""
        _run_mysqlsh_script.side_effect = MySQLClientError("Error escalating user privileges")

        with self.assertRaises(MySQLEscalateUserPrivilegesError):
            self.mysql.escalate_user_privileges("test_user")

    @patch("mysql_k8s_helpers.MySQL._run_mysqlcli_script")
    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    def test_delete_users_with_label(self, _run_mysqlsh_script, _run_mysqlcli_script):
        """Test successful execution of delete_users_with_label."""
        _expected_get_label_users_commands = (
            "SELECT CONCAT(user.user, '@', user.host) FROM mysql.user AS user "
            "JOIN information_schema.user_attributes AS attributes"
            " ON (user.user = attributes.user AND user.host = attributes.host) "
            'WHERE attributes.attribute LIKE \'%"test_label_name": "test_label_value"%\'',
        )

        _run_mysqlcli_script.return_value = "users\ntest_user@%\ntest_user_2@localhost"

        _expected_drop_users_commands = (
            "shell.connect_to_primary('serverconfig:serverconfigpassword@127.0.0.1')",
            "session.run_sql(\"DROP USER IF EXISTS 'test_user'@'%', 'test_user_2'@'localhost';\")",
        )

        self.mysql.delete_users_with_label("test_label_name", "test_label_value")

        _run_mysqlcli_script.assert_called_once_with(
            "; ".join(_expected_get_label_users_commands),
            user="serverconfig",
            password="serverconfigpassword",
        )
        _run_mysqlsh_script.assert_called_once_with("\n".join(_expected_drop_users_commands))

    @patch("mysql_k8s_helpers.MySQL._run_mysqlcli_script")
    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    def test_delete_users_with_label_exception(self, _run_mysqlsh_script, _run_mysqlcli_script):
        """Test exception while executing delete_users_with_label."""
        _run_mysqlcli_script.side_effect = MySQLClientError("Error getting label users")

        with self.assertRaises(MySQLDeleteUsersWithLabelError):
            self.mysql.delete_users_with_label("test_label_name", "test_label_value")

        _run_mysqlcli_script.reset_mock()
        _run_mysqlsh_script.side_effect = MySQLClientError("Error dropping users")

        with self.assertRaises(MySQLDeleteUsersWithLabelError):
            self.mysql.delete_users_with_label("test_label_name", "test_label_value")

    @patch("ops.model.Container")
    def test_run_mysqlsh_script(self, _container):
        """Test a successful execution of run_mysqlsh_script."""
        _container.exec.return_value = MagicMock()
        _container.exec.return_value.wait_output.return_value = (
            b"stdout",
            b"stderr",
        )
        self.mysql.container = _container

        self.mysql._run_mysqlsh_script("script")

        _container.exec.assert_called_once_with(
            [
                "/usr/bin/mysqlsh",
                "--no-wizard",
                "--python",
                "--verbose=1",
                "-f",
                MYSQLSH_SCRIPT_FILE,
                ";",
                "rm",
                MYSQLSH_SCRIPT_FILE,
            ],
            timeout=None,
        )

    @patch("ops.model.Container")
    def test_run_mysqlcli_script(self, _container):
        """Test a execution of run_mysqlcli_script."""
        _container.exec.return_value = MagicMock()
        _container.exec.return_value.wait_output.return_value = (
            b"stdout",
            b"stderr",
        )
        self.mysql.container = _container

        self.mysql._run_mysqlcli_script("script")

        _container.exec.assert_called_once_with(
            [
                "/usr/bin/mysql",
                "-u",
                "root",
                "--protocol=SOCKET",
                f"--socket={MYSQLD_SOCK_FILE}",
                "-e",
                "script",
            ],
            timeout=None,
        )

    @patch("mysql_k8s_helpers.MySQL.get_cluster_status", return_value=GET_CLUSTER_STATUS_RETURN)
    def test_wait_until_unit_removed_from_cluster(self, _get_cluster_status):
        """Test the successful execution of _wait_until_unit_removed_from_cluster."""
        self.mysql._wait_until_unit_removed_from_cluster("mysql-3.mysql-endpoints")

        self.assertEqual(_get_cluster_status.call_count, 1)

    @patch("mysql_k8s_helpers.MySQL.get_cluster_status", return_value=GET_CLUSTER_STATUS_RETURN)
    def test_wait_until_unit_removed_from_cluster_exception(self, _get_cluster_status):
        """Test an exception while executing _wait_until_unit_removed_from_cluster."""
        # disable tenacity retry
        self.mysql._wait_until_unit_removed_from_cluster.retry.retry = (
            tenacity.retry_if_not_result(lambda x: True)
        )

        with self.assertRaises(MySQLWaitUntilUnitRemovedFromClusterError):
            self.mysql._wait_until_unit_removed_from_cluster("mysql-0.mysql-endpoints")

        self.assertEqual(_get_cluster_status.call_count, 1)

        _get_cluster_status.reset_mock()
        _get_cluster_status.return_value = None

        with self.assertRaises(MySQLWaitUntilUnitRemovedFromClusterError):
            self.mysql._wait_until_unit_removed_from_cluster("mysql-0.mysql-endpoints")
