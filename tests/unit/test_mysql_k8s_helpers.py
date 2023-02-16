# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from unittest.mock import MagicMock, call, patch

import tenacity
from charms.mysql.v0.mysql import (
    MySQLClientError,
    MySQLConfigureInstanceError,
    MySQLConfigureMySQLUsersError,
)
from ops.pebble import ExecError

from mysql_k8s_helpers import (
    MYSQLD_SOCK_FILE,
    MYSQLSH_SCRIPT_FILE,
    MySQL,
    MySQLCreateDatabaseError,
    MySQLCreateUserError,
    MySQLDeleteUsersWithLabelError,
    MySQLEscalateUserPrivilegesError,
    MySQLForceRemoveUnitFromClusterError,
    MySQLInitialiseMySQLDError,
    MySQLServiceNotRunningError,
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
            "password",
            "serverconfig",
            "serverconfigpassword",
            "clusteradmin",
            "clusteradminpassword",
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
            command=["mysqld", "--initialize-insecure", "-u", "mysql"]
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

    @patch("ops.model.Container")
    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    @patch("mysql_k8s_helpers.MySQL._run_mysqlcli_script")
    @patch("mysql_k8s_helpers.MySQL.wait_until_mysql_connection")
    def test_configure_instance(
        self, _wait_until_mysql_connection, _run_mysqlcli_script, _run_mysqlsh_script, _container
    ):
        """Test a successful execution of configure_instance."""
        configure_instance_commands = (
            'dba.configure_instance(\'serverconfig:serverconfigpassword@127.0.0.1\', {"restart": "false", "clusterAdmin": "clusteradmin", "clusterAdminPassword": "clusteradminpassword"})',
        )
        self.mysql.container = _container

        self.mysql.configure_instance()

        _run_mysqlsh_script.assert_called_once_with("\n".join(configure_instance_commands))
        _wait_until_mysql_connection.assert_called_once()

    @patch("ops.model.Container")
    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    @patch("mysql_k8s_helpers.MySQL.wait_until_mysql_connection")
    def test_configure_instance_exceptions(
        self, _wait_until_mysql_connection, _run_mysqlsh_script, _container
    ):
        """Test exceptions raise while running configure_instance."""
        # Test an issue with _run_mysqlsh_script
        _run_mysqlsh_script.side_effect = MySQLClientError("Error running mysqlsh")

        self.mysql.container = _container

        with self.assertRaises(MySQLConfigureInstanceError):
            self.mysql.configure_instance()

        _wait_until_mysql_connection.assert_not_called()

        # Reset mocks
        _run_mysqlsh_script.reset_mock()
        _wait_until_mysql_connection.reset_mock()

        # Test an issue with _wait_until_mysql_connection
        _wait_until_mysql_connection.side_effect = MySQLServiceNotRunningError()

        with self.assertRaises(MySQLConfigureInstanceError):
            self.mysql.configure_instance()

        _run_mysqlsh_script.assert_called_once()

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

    @patch("mysql_k8s_helpers.MySQL.get_cluster_primary_address", return_value="1.1.1.1:3306")
    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    def test_create_database(self, _run_mysqlsh_script, _get_cluster_primary_address):
        """Test successful execution of create_database."""
        _expected_create_database_commands = (
            "shell.connect('serverconfig:serverconfigpassword@1.1.1.1:3306')",
            'session.run_sql("CREATE DATABASE IF NOT EXISTS `test_database`;")',
        )

        self.mysql.create_database("test_database")

        _run_mysqlsh_script.assert_called_once_with("\n".join(_expected_create_database_commands))

    @patch("mysql_k8s_helpers.MySQL.get_cluster_primary_address", return_value="1.1.1.1:3306")
    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    def test_create_database_exception(self, _run_mysqlsh_script, _get_cluster_primary_address):
        """Test exception while executing create_database."""
        _run_mysqlsh_script.side_effect = MySQLClientError("Error creating database")

        with self.assertRaises(MySQLCreateDatabaseError):
            self.mysql.create_database("test_database")

    @patch("mysql_k8s_helpers.MySQL.get_cluster_primary_address", return_value="1.1.1.1:3306")
    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    def test_create_user(self, _run_mysqlsh_script, _get_cluster_primary_address):
        """Test successful execution of create_user."""
        _escaped_attributes = json.dumps({"label": "test_label"}).replace('"', r"\"")
        _expected_create_user_commands = (
            "shell.connect('serverconfig:serverconfigpassword@1.1.1.1:3306')",
            f"session.run_sql(\"CREATE USER `test_user`@`%` IDENTIFIED BY 'test_password' ATTRIBUTE '{_escaped_attributes}';\")",
        )

        self.mysql.create_user("test_user", "test_password", "test_label")

        _run_mysqlsh_script.assert_called_once_with("\n".join(_expected_create_user_commands))

    @patch("mysql_k8s_helpers.MySQL.get_cluster_primary_address", return_value="1.1.1.1:3306")
    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    def test_create_user_exception(self, _run_mysqlsh_script, _get_cluster_primary_address):
        """Test exception while executing create_user."""
        _run_mysqlsh_script.side_effect = MySQLClientError("Error creating user")

        with self.assertRaises(MySQLCreateUserError):
            self.mysql.create_user("test_user", "test_password", "test_label")

    @patch("mysql_k8s_helpers.MySQL.get_cluster_primary_address", return_value="1.1.1.1:3306")
    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    def test_escalate_user_privileges(self, _run_mysqlsh_script, _get_cluster_primary_address):
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
            "shell.connect('serverconfig:serverconfigpassword@1.1.1.1:3306')",
            'session.run_sql("GRANT ALL ON *.* TO `test_user`@`%` WITH GRANT OPTION;")',
            f"session.run_sql(\"REVOKE {', '.join(super_privileges_to_revoke)} ON *.* FROM `test_user`@`%`;\")",
            'session.run_sql("FLUSH PRIVILEGES;")',
        )

        self.mysql.escalate_user_privileges("test_user")

        _run_mysqlsh_script.assert_called_once_with(
            "\n".join(_expected_escalate_user_privileges_commands)
        )

    @patch("mysql_k8s_helpers.MySQL.get_cluster_primary_address", return_value="1.1.1.1:3306")
    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    def test_escalate_user_privileges_exception(
        self, _run_mysqlsh_script, _get_cluster_primary_address
    ):
        """Test exception while executing escalate_user_privileges."""
        _run_mysqlsh_script.side_effect = MySQLClientError("Error escalating user privileges")

        with self.assertRaises(MySQLEscalateUserPrivilegesError):
            self.mysql.escalate_user_privileges("test_user")

    @patch("mysql_k8s_helpers.MySQL.get_cluster_primary_address", return_value="1.1.1.1:3306")
    @patch("mysql_k8s_helpers.MySQL._run_mysqlcli_script")
    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    def test_delete_users_with_label(
        self, _run_mysqlsh_script, _run_mysqlcli_script, _get_cluster_primary_address
    ):
        """Test successful execution of delete_users_with_label."""
        _expected_get_label_users_commands = (
            "SELECT CONCAT(user.user, '@', user.host) FROM mysql.user AS user "
            "JOIN information_schema.user_attributes AS attributes"
            " ON (user.user = attributes.user AND user.host = attributes.host) "
            'WHERE attributes.attribute LIKE \'%"test_label_name": "test_label_value"%\'',
        )

        _run_mysqlcli_script.return_value = "users\ntest_user@%\ntest_user_2@localhost"

        _expected_drop_users_commands = (
            "shell.connect('serverconfig:serverconfigpassword@1.1.1.1:3306')",
            "session.run_sql(\"DROP USER IF EXISTS 'test_user'@'%', 'test_user_2'@'localhost';\")",
        )

        self.mysql.delete_users_with_label("test_label_name", "test_label_value")

        _run_mysqlcli_script.assert_called_once_with(
            "; ".join(_expected_get_label_users_commands),
            user="serverconfig",
            password="serverconfigpassword",
        )
        _run_mysqlsh_script.assert_called_once_with("\n".join(_expected_drop_users_commands))

    @patch("mysql_k8s_helpers.MySQL.get_cluster_primary_address", return_value="1.1.1.1:3306")
    @patch("mysql_k8s_helpers.MySQL._run_mysqlcli_script")
    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    def test_delete_users_with_label_exception(
        self, _run_mysqlsh_script, _run_mysqlcli_script, _get_cluster_primary_address
    ):
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
            ]
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
            ]
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

    @patch("mysql_k8s_helpers.MySQL.get_cluster_status", return_value=GET_CLUSTER_STATUS_RETURN)
    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    @patch("mysql_k8s_helpers.MySQL._wait_until_unit_removed_from_cluster")
    def test_force_remove_unit_from_cluster(
        self, _wait_until_unit_removed_from_cluster, _run_mysqlsh_script, _get_cluster_status
    ):
        """Test the successful execution of force_remove_unit_from_cluster."""
        _expected_remove_instance_commands = "\n".join(
            (
                "shell.connect('clusteradmin:clusteradminpassword@127.0.0.1')",
                "cluster = dba.get_cluster('test_cluster')",
                'cluster.remove_instance(\'1.2.3.4\', {"force": "true"})',
            )
        )

        _expected_force_quorum_commands = "\n".join(
            (
                "shell.connect('clusteradmin:clusteradminpassword@127.0.0.1')",
                "cluster = dba.get_cluster('test_cluster')",
                "cluster.force_quorum_using_partition_of('clusteradmin@127.0.0.1', 'clusteradminpassword')",
            )
        )

        self.mysql.force_remove_unit_from_cluster("1.2.3.4")

        self.assertEqual(_get_cluster_status.call_count, 1)
        self.assertEqual(_run_mysqlsh_script.call_count, 2)
        self.assertEqual(_wait_until_unit_removed_from_cluster.call_count, 1)
        self.assertEqual(
            sorted(_run_mysqlsh_script.mock_calls),
            sorted(
                [
                    call(_expected_remove_instance_commands),
                    call(_expected_force_quorum_commands),
                ]
            ),
        )

    @patch("mysql_k8s_helpers.MySQL.get_cluster_status", return_value=GET_CLUSTER_STATUS_RETURN)
    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    @patch("mysql_k8s_helpers.MySQL._wait_until_unit_removed_from_cluster")
    def test_force_remove_unit_from_cluster_exception(
        self, _wait_until_unit_removed_from_cluster, _run_mysqlsh_script, _get_cluster_status
    ):
        """Test exceptions raised when executing force_remove_unit_from_cluster."""
        _get_cluster_status.return_value = None

        with self.assertRaises(MySQLForceRemoveUnitFromClusterError):
            self.mysql.force_remove_unit_from_cluster("1.2.3.4")

        self.assertEqual(_get_cluster_status.call_count, 1)
        self.assertEqual(_run_mysqlsh_script.call_count, 0)
        self.assertEqual(_wait_until_unit_removed_from_cluster.call_count, 0)

        _get_cluster_status.reset_mock()
        _get_cluster_status.return_value = GET_CLUSTER_STATUS_RETURN
        _run_mysqlsh_script.side_effect = MySQLClientError("Mock error")

        with self.assertRaises(MySQLForceRemoveUnitFromClusterError):
            self.mysql.force_remove_unit_from_cluster("1.2.3.4")

        self.assertEqual(_get_cluster_status.call_count, 1)
        self.assertEqual(_run_mysqlsh_script.call_count, 1)
        self.assertEqual(_wait_until_unit_removed_from_cluster.call_count, 0)

        _get_cluster_status.reset_mock()
        _get_cluster_status.return_value = GET_CLUSTER_STATUS_RETURN
        _run_mysqlsh_script.reset_mock()
        _run_mysqlsh_script.side_effect = None
        _wait_until_unit_removed_from_cluster.side_effect = (
            MySQLWaitUntilUnitRemovedFromClusterError("Mock error")
        )

        with self.assertRaises(MySQLForceRemoveUnitFromClusterError):
            self.mysql.force_remove_unit_from_cluster("1.2.3.4")

        self.assertEqual(_get_cluster_status.call_count, 1)
        self.assertEqual(_run_mysqlsh_script.call_count, 2)
        self.assertEqual(_wait_until_unit_removed_from_cluster.call_count, 1)
