# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

from ops.pebble import ExecError

from mysqlsh_helpers import (
    MySQL,
    MySQLConfigureMySQLUsersError,
    MySQLInstanceConfigureError,
)


class TestMySQL(unittest.TestCase):
    def setUp(self):
        root_password = "password"
        cluster_admin_user = "clusteradmin"
        cluster_admin_password = "innodb"
        instance_address = "127.0.0.1"

        self.mysql = MySQL(
            root_password, cluster_admin_user, cluster_admin_password, instance_address
        )

    @patch("mysqlsh_helpers.MySQL._run_mysqlcli_script")
    def test_configure_mysql_users(self, _run_mysqlcli_script):
        """Test failed to configuring the MySQL users."""
        _run_mysqlcli_script.return_value = b""
        _expected_script = " ".join(
            (
                "SET @@SESSION.SQL_LOG_BIN=0;",
                "CREATE USER 'cadmin'@'10.1.1.1' IDENTIFIED BY 'test';",
                "GRANT ALL ON *.* TO 'cadmin'@'10.1.1.1' WITH GRANT OPTION;",
                "CREATE USER 'root'@'%' IDENTIFIED BY 'test';",
                "GRANT ALL ON *.* TO 'root'@'%' WITH GRANT OPTION;",
                "UPDATE mysql.user SET authentication_string=null WHERE User='root' and Host='localhost';",
                "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY 'test';",
                "REVOKE SYSTEM_USER ON *.* FROM root@'%';",
                "REVOKE SYSTEM_USER ON *.* FROM root@localhost;",
                "FLUSH PRIVILEGES;",
            )
        )

        _m = MySQL("test", "cadmin", "test", "10.1.1.1")

        _m.configure_mysql_users()
        _run_mysqlcli_script.assert_called_once_with(_expected_script)

    @patch("mysqlsh_helpers.MySQL._run_mysqlcli_script")
    def test_configure_mysql_users_fail(self, _run_mysqlcli_script):
        """Test failed to configuring the MySQL users."""
        _run_mysqlcli_script.side_effect = ExecError("mysqlsh", -1, "", "")

        _m = MySQL("test", "test", "test", "10.1.1.1")
        with self.assertRaises(MySQLConfigureMySQLUsersError):
            _m.configure_mysql_users()

    @patch("mysqlsh_helpers.MySQL._run_mysqlsh_script")
    @patch("mysqlsh_helpers.MySQL._wait_until_mysql_connection")
    def test_configure_instance(self, _wait_until_mysql_connection, _run_mysqlsh_script):
        """Test a successful execution of configure_instance."""
        configure_instance_commands = (
            "dba.configure_instance('clusteradmin:innodb@127.0.0.1')",
            "my_shell = shell.connect('clusteradmin:innodb@127.0.0.1')",
            'my_shell.run_sql("RESTART;");',
        )

        self.mysql.configure_instance()

        _run_mysqlsh_script.assert_called_once_with("\n".join(configure_instance_commands))
        _wait_until_mysql_connection.assert_called_once()

    @patch("mysqlsh_helpers.MySQL._run_mysqlsh_script")
    @patch("mysqlsh_helpers.MySQL._wait_until_mysql_connection")
    def test_configure_instance_exceptions(
        self, _wait_until_mysql_connection, _run_mysqlsh_script
    ):
        """Test exceptions raised by methods called in configure_instance."""
        # Test an issue with _run_mysqlsh_script
        _run_mysqlsh_script.side_effect = ExecError("mysqlsh", -1, "", "")

        with self.assertRaises(MySQLInstanceConfigureError):
            self.mysql.configure_instance()

        _wait_until_mysql_connection.assert_not_called()

        # Reset mocks
        _run_mysqlsh_script.reset_mock()
        _wait_until_mysql_connection.reset_mock()

        # Test an issue with _wait_until_mysql_connection
        _wait_until_mysql_connection.side_effect = ExecError("mysqlsh", -1, "", "")

        with self.assertRaises(MySQLInstanceConfigureError):
            self.mysql.configure_instance()

        _run_mysqlsh_script.assert_called_once()
