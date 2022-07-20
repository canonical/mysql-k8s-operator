# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import MagicMock, call, patch

import tenacity
from charms.mysql.v0.mysql import (
    MySQLClientError,
    MySQLConfigureInstanceError,
    MySQLConfigureMySQLUsersError,
)
from ops.pebble import ExecError

from mysqlsh_helpers import (
    MYSQLD_SOCK_FILE,
    MYSQLSH_SCRIPT_FILE,
    MySQL,
    MySQLInitialiseMySQLDError,
    MySQLRemoveInstancesNotOnlineRetryError,
    MySQLServiceNotRunningError,
)

GET_CLUSTER_STATUS_RETURN = {
    "defaultreplicaset": {
        "status": "no_quorum",
        "topology": {
            "mysql-0": {
                "status": "online",
                "address": "mysql-1.mysql-endpoints",
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
    @patch("mysqlsh_helpers.MySQL._run_mysqlsh_script")
    @patch("mysqlsh_helpers.MySQL._run_mysqlcli_script")
    @patch("mysqlsh_helpers.MySQL.wait_until_mysql_connection")
    def test_configure_instance(
        self, _wait_until_mysql_connection, _run_mysqlcli_script, _run_mysqlsh_script, _container
    ):
        """Test a successful execution of configure_instance."""
        configure_instance_commands = (
            'dba.configure_instance(\'serverconfig:serverconfigpassword@127.0.0.1\', {"clusterAdmin": "clusteradmin", "clusterAdminPassword": "clusteradminpassword", "restart": "false"})',
        )
        self.mysql.container = _container

        self.mysql.configure_instance()

        _run_mysqlsh_script.assert_called_once_with("\n".join(configure_instance_commands))
        _wait_until_mysql_connection.assert_called_once()

    @patch("ops.model.Container")
    @patch("mysqlsh_helpers.MySQL._run_mysqlsh_script")
    @patch("mysqlsh_helpers.MySQL.wait_until_mysql_connection")
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

    @patch("mysqlsh_helpers.MySQL._run_mysqlcli_script")
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

    @patch("mysqlsh_helpers.MySQL._run_mysqlcli_script")
    def test_configure_mysql_users_exception(self, _run_mysqlcli_script):
        """Test exceptions trying to configuring the MySQL users."""
        _run_mysqlcli_script.side_effect = MySQLClientError("Error running mysql")

        with self.assertRaises(MySQLConfigureMySQLUsersError):
            self.mysql.configure_mysql_users()

    @patch("mysqlsh_helpers.MySQL._wait_till_all_members_are_online")
    @patch("mysqlsh_helpers.MySQL.get_cluster_status")
    @patch("mysqlsh_helpers.MySQL._run_mysqlsh_script")
    def test_remove_instances_not_online(
        self, _run_mysqlsh_script, _get_cluster_status, _wait_till_all_members_are_online
    ):
        """Test a successful execution of remove_instances_not_online."""
        _get_cluster_status.return_value = GET_CLUSTER_STATUS_RETURN

        _expected_force_quorum_commands = "\n".join(
            (
                "shell.connect('clusteradmin:clusteradminpassword@127.0.0.1')",
                "cluster = dba.get_cluster('test_cluster')",
                "cluster.force_quorum_using_partition_of('clusteradmin@mysql-1.mysql-endpoints', 'clusteradminpassword')",
            )
        )

        _expected_remove_instance_one_commands = "\n".join(
            (
                "shell.connect('clusteradmin:clusteradminpassword@127.0.0.1')",
                "cluster = dba.get_cluster('test_cluster')",
                'cluster.remove_instance(\'mysql-1.mysql-endpoints\', {"force": "true"})',
            )
        )
        _expected_remove_instance_two_commands = "\n".join(
            (
                "shell.connect('clusteradmin:clusteradminpassword@127.0.0.1')",
                "cluster = dba.get_cluster('test_cluster')",
                'cluster.remove_instance(\'mysql-2.mysql-endpoints\', {"force": "true"})',
            )
        )

        # disable tenacity retry
        self.mysql.remove_instances_not_online.retry.retry = tenacity.retry_if_not_result(
            lambda x: True
        )

        self.mysql.remove_instances_not_online()

        self.assertEqual(_run_mysqlsh_script.call_count, 3)

        self.assertEqual(
            sorted(_run_mysqlsh_script.mock_calls),
            sorted(
                [
                    call(_expected_force_quorum_commands),
                    call(_expected_remove_instance_one_commands),
                    call(_expected_remove_instance_two_commands),
                ]
            ),
        )

    @patch("mysqlsh_helpers.MySQL.get_cluster_status")
    @patch("mysqlsh_helpers.MySQL._run_mysqlsh_script")
    def test_remove_instances_not_online_exception(self, _run_mysqlsh_script, _get_cluster_status):
        """Test an exception while executing remove_instances_not_online."""
        # disable tenacity retry
        self.mysql.remove_instances_not_online.retry.retry = tenacity.retry_if_not_result(
            lambda x: True
        )

        _get_cluster_status.return_value = None
        with self.assertRaises(MySQLRemoveInstancesNotOnlineRetryError):
            self.mysql.remove_instances_not_online()

        _get_cluster_status.return_value = GET_CLUSTER_STATUS_RETURN
        _run_mysqlsh_script.side_effect = MySQLClientError("Error running mysqlsh")

        with self.assertRaises(MySQLRemoveInstancesNotOnlineRetryError):
            self.mysql.remove_instances_not_online()

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
