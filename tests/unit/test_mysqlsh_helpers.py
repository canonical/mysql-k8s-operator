# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import unittest
from unittest.mock import MagicMock, call, patch

from ops.pebble import ExecError

from mysqlsh_helpers import (
    MYSQLD_SOCK_FILE,
    MySQL,
    MySQLAddInstanceToClusterError,
    MySQLBootstrapInstanceError,
    MySQLConfigureInstanceError,
    MySQLConfigureMySQLUsersError,
    MySQLCreateClusterError,
    MySQLPatchDNSSearchesError,
    MySQLServiceNotRunningError,
    MYSQLSH_SCRIPT_FILE,
)


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

    @patch("mysqlsh_helpers.MySQL._run_mysqlcli_script")
    def test_configure_mysql_users(self, _run_mysqlcli_script):
        """Test failed to configuring the MySQL users."""
        _expected_configure_user_commands = " ".join(
            (
                "CREATE USER 'root'@'%' IDENTIFIED BY 'password';",
                "GRANT ALL ON *.* TO 'root'@'%' WITH GRANT OPTION;",
                "CREATE USER 'serverconfig'@'%' IDENTIFIED BY 'serverconfigpassword';",
                "GRANT ALL ON *.* TO 'serverconfig'@'%' WITH GRANT OPTION;",
                "UPDATE mysql.user SET authentication_string=null WHERE User='root' and Host='localhost';",
                "ALTER USER 'root'@'localhost' IDENTIFIED BY 'password';",
                "REVOKE SYSTEM_USER, SYSTEM_VARIABLES_ADMIN, SUPER, REPLICATION_SLAVE_ADMIN, GROUP_REPLICATION_ADMIN, BINLOG_ADMIN, SET_USER_ID, ENCRYPTION_KEY_ADMIN, VERSION_TOKEN_ADMIN, CONNECTION_ADMIN ON *.* FROM 'root'@'%';",
                "REVOKE SYSTEM_USER, SYSTEM_VARIABLES_ADMIN, SUPER, REPLICATION_SLAVE_ADMIN, GROUP_REPLICATION_ADMIN, BINLOG_ADMIN, SET_USER_ID, ENCRYPTION_KEY_ADMIN, VERSION_TOKEN_ADMIN, CONNECTION_ADMIN ON *.* FROM 'root'@'localhost';",
                "FLUSH PRIVILEGES;",
            )
        )

        self.mysql.configure_mysql_users()

        self.assertEqual(_run_mysqlcli_script.call_count, 1)

        self.assertEqual(
            sorted(_run_mysqlcli_script.mock_calls),
            sorted(
                [
                    call(_expected_configure_user_commands),
                ]
            ),
        )

    @patch("mysqlsh_helpers.MySQL._run_mysqlcli_script")
    def test_configure_mysql_users_fail(self, _run_mysqlcli_script):
        """Test failed to configuring the MySQL users."""
        _run_mysqlcli_script.side_effect = ExecError(
            command=["mysql"], exit_code=1, stdout=b"", stderr=b"Error"
        )

        with self.assertRaises(MySQLConfigureMySQLUsersError):
            self.mysql.configure_mysql_users()

    @patch("ops.model.Container")
    @patch("mysqlsh_helpers.MySQL._run_mysqlsh_script")
    @patch("mysqlsh_helpers.MySQL._wait_until_mysql_connection")
    def test_configure_instance(
        self, _wait_until_mysql_connection, _run_mysqlsh_script, _container
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
    @patch("mysqlsh_helpers.MySQL._wait_until_mysql_connection")
    def test_configure_instance_exceptions(
        self, _wait_until_mysql_connection, _run_mysqlsh_script, _container
    ):
        """Test exceptions raise while running configure_instance."""
        # Test an issue with _run_mysqlsh_script
        _run_mysqlsh_script.side_effect = ExecError(
            command=["mysqlsh"], exit_code=1, stdout=b"", stderr=b"Error"
        )

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

    @patch("mysqlsh_helpers.MySQL._run_mysqlsh_script")
    def test_create_cluster(self, _run_mysqlsh_script):
        """Test a successful execution of create_cluster."""
        create_cluster_commands = (
            "shell.connect('serverconfig:serverconfigpassword@127.0.0.1')",
            "dba.create_cluster('test_cluster')",
        )

        self.mysql.create_cluster()

        _run_mysqlsh_script.assert_called_once_with("\n".join(create_cluster_commands))

    @patch("mysqlsh_helpers.MySQL._run_mysqlsh_script")
    def test_create_cluster_exceptions(self, _run_mysqlsh_script):
        """Test exceptions raised while running create_cluster."""
        _run_mysqlsh_script.side_effect = ExecError(
            command=["mysqlsh"], exit_code=1, stdout=b"", stderr=b"Error"
        )

        with self.assertRaises(MySQLCreateClusterError):
            self.mysql.create_cluster()

    @patch("mysqlsh_helpers.MySQL._run_mysqlsh_script")
    def test_add_instance_to_cluster(self, _run_mysqlsh_script):
        """Test a successful execution of create_cluster."""
        add_instance_to_cluster_commands = (
            "shell.connect('clusteradmin:clusteradminpassword@127.0.0.1')",
            "cluster = dba.get_cluster('test_cluster')",
            'cluster.add_instance(\'clusteradmin@127.0.0.2\', {"password": "clusteradminpassword", "recoveryMethod": "auto"})',
        )

        self.mysql.add_instance_to_cluster("127.0.0.2")

        _run_mysqlsh_script.assert_called_once_with("\n".join(add_instance_to_cluster_commands))

    @patch("mysqlsh_helpers.MySQL._run_mysqlsh_script")
    def test_add_instance_to_cluster_exception(self, _run_mysqlsh_script):
        """Test exceptions raised while running add_instance_to_cluster."""
        _run_mysqlsh_script.side_effect = ExecError(
            command=["mysqlsh"], exit_code=1, stdout=b"", stderr=b"Error"
        )

        with self.assertRaises(MySQLAddInstanceToClusterError):
            self.mysql.add_instance_to_cluster("127.0.0.2")

    @patch("ops.pebble.ExecProcess")
    @patch("ops.model.Container")
    def test_bootstrap_instance(self, _container, _process):
        """Test a successful execution of bootstrap_instance."""
        _container.exec.return_value = _process
        self.mysql.container = _container

        self.mysql.bootstrap_instance()

        _container.exec.assert_called_once_with(
            command=["mysqld", "--initialize-insecure", "-u", "mysql"]
        )

        _process.wait_output.assert_called_once()

    @patch("ops.model.Container")
    def test_bootstrap_instance_exception(self, _container):
        """Test a failing execution of bootstrap_instance."""
        _container.exec.side_effect = ExecError(
            command=["mysqld"], exit_code=1, stdout=b"", stderr=b"Error"
        )
        self.mysql.container = _container

        with self.assertRaises(MySQLBootstrapInstanceError):
            self.mysql.bootstrap_instance()

    @patch("ops.pebble.ExecProcess")
    @patch("ops.model.Container")
    def test_patch_dns_searches(self, _container, _process):
        """Test a successful execution of patch_dns_searches."""
        mock_file = MagicMock()
        mock_file.read.return_value = "\n".join(
            (
                "search dev.svc.cluster.local svc.cluster.local cluster.local",
                "nameserver 10.152.183.10",
                "options ndots:5",
            )
        )
        _container.pull.return_value = mock_file
        _container.exec.return_value = _process

        self.mysql.container = _container

        self.mysql.patch_dns_searches("app-name")

        _container.push.assert_called_once_with(
            "/etc/resolv.conf-new",
            source="\n".join(
                (
                    "search app-name-endpoints.dev.svc.cluster.local dev.svc.cluster.local svc.cluster.local cluster.local",
                    "nameserver 10.152.183.10",
                    "options ndots:5",
                    "",
                )
            ),
        )

    @patch("ops.model.Container")
    def test_patch_dns_searches_exception(self, _container):
        """Test a failing execution of patch_dns_searches."""
        _container.pull.side_effect = Exception()
        self.mysql.container = _container

        with self.assertRaises(MySQLPatchDNSSearchesError):
            self.mysql.patch_dns_searches("app-name")

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
