# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from unittest.mock import MagicMock, call, patch

import tenacity
from charms.mysql.v0.mysql import MySQLClientError
from ops.pebble import ExecError, PathError

from constants import PEER
from mysql_k8s_helpers import (
    MYSQLD_SOCK_FILE,
    MySQL,
    MySQLCreateDatabaseError,
    MySQLCreateUserError,
    MySQLDeleteUsersWithLabelError,
    MySQLEscalateUserPrivilegesError,
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
            command=["/usr/sbin/mysqld", "--initialize", "-u", "mysql"],
            user="mysql",
            group="mysql",
        )

        _process.wait.assert_called_once()

    @patch("ops.model.Container")
    def test_initialise_mysqld_exception(self, _container):
        """Test a failing execution of bootstrap_instance."""
        self.mysql.initialise_mysqld.retry.retry = tenacity.retry_if_not_result(lambda x: True)
        _container.exec.side_effect = ExecError(
            command=["mysqld"], exit_code=1, stdout=b"", stderr=b"Error"
        )
        self.mysql.container = _container

        with self.assertRaises(MySQLInitialiseMySQLDError):
            self.mysql.initialise_mysqld()

    @patch("ops.model.Container")
    def test_wait_until_mysql_connection(self, _container):
        """Test wait_until_mysql_connection."""
        self.mysql.wait_until_mysql_connection.retry.retry = tenacity.retry_if_not_result(
            lambda x: True
        )
        _container.exists.return_value = True
        self.mysql.container = _container

        self.assertTrue(not self.mysql.wait_until_mysql_connection(check_port=False))

    @patch("mysql_k8s_helpers.MySQL._run_mysqlsh_script")
    def test_create_database(self, _run_mysqlsh_script):
        """Test successful execution of create_database."""
        _expected_create_database_commands = (
            "shell.connect_to_primary()",
            'session.run_sql("CREATE DATABASE IF NOT EXISTS `test_database`;")',
        )

        self.mysql.create_database("test_database")

        _run_mysqlsh_script.assert_called_once_with(
            "\n".join(_expected_create_database_commands),
            user="serverconfig",
            host="127.0.0.1",
            password="serverconfigpassword",
        )

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
            "shell.connect_to_primary()",
            f"session.run_sql(\"CREATE USER `test_user`@`%` IDENTIFIED BY 'test_password' ATTRIBUTE '{_escaped_attributes}';\")",
        )

        self.mysql.create_user("test_user", "test_password", "test_label")

        _run_mysqlsh_script.assert_called_once_with(
            "\n".join(_expected_create_user_commands),
            user="serverconfig",
            host="127.0.0.1",
            password="serverconfigpassword",
        )

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
            "shell.connect_to_primary()",
            'session.run_sql("GRANT ALL ON *.* TO `test_user`@`%` WITH GRANT OPTION;")',
            f'session.run_sql("REVOKE {", ".join(super_privileges_to_revoke)} ON *.* FROM `test_user`@`%`;")',
            'session.run_sql("FLUSH PRIVILEGES;")',
        )

        self.mysql.escalate_user_privileges("test_user")

        _run_mysqlsh_script.assert_called_once_with(
            "\n".join(_expected_escalate_user_privileges_commands),
            user="serverconfig",
            host="127.0.0.1",
            password="serverconfigpassword",
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

        _run_mysqlcli_script.return_value = [
            [
                "test_user@%",
            ],
            [
                "test_user_2@localhost",
            ],
        ]

        _expected_drop_users_commands = (
            "shell.connect_to_primary()",
            "session.run_sql(\"DROP USER IF EXISTS 'test_user'@'%', 'test_user_2'@'localhost';\")",
        )

        self.mysql.delete_users_with_label("test_label_name", "test_label_value")

        _run_mysqlcli_script.assert_called_once_with(
            _expected_get_label_users_commands,
            user="serverconfig",
            password="serverconfigpassword",
        )
        _run_mysqlsh_script.assert_called_once_with(
            "\n".join(_expected_drop_users_commands),
            user="serverconfig",
            host="127.0.0.1",
            password="serverconfigpassword",
        )

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
            "garbage_that_mysqlsh_output###stdout",
            "stderr",
        )
        self.mysql.container = _container

        self.mysql._run_mysqlsh_script(
            "script", user="serverconfig", password="serverconfigpassword", host="127.0.0.1:3306"
        )

        call_script = "shell.options.set('useWizards', False)\nprint('###')\nscript"
        _container.exec.assert_called_once_with(
            [
                "/usr/bin/mysqlsh",
                "--passwords-from-stdin",
                "--uri=serverconfig@127.0.0.1:3306",
                "--python",
                "--verbose=0",
                "-c",
                call_script,
            ],
            stdin="serverconfigpassword",
        )

        _container.reset_mock()
        output = self.mysql._run_mysqlsh_script(
            "script",
            user="serverconfig",
            password="serverconfigpassword",
            host="127.0.0.1:3306",
            timeout=10,
        )
        self.assertEqual(output, "stdout")

        _container.exec.assert_called_once_with(
            [
                "timeout",
                "10",
                "/usr/bin/mysqlsh",
                "--passwords-from-stdin",
                "--uri=serverconfig@127.0.0.1:3306",
                "--python",
                "--verbose=0",
                "-c",
                call_script,
            ],
            stdin="serverconfigpassword",
        )

    @patch("ops.model.Container")
    def test_run_mysqlcli_script(self, _container):
        """Test a execution of run_mysqlcli_script."""
        _container.exec.return_value = MagicMock()
        _container.exec.return_value.wait_output.return_value = (
            "",
            None,
        )
        self.mysql.container = _container

        self.mysql._run_mysqlcli_script(("script",))

        _container.exec.assert_called_once_with(
            [
                "/usr/bin/mysql",
                "-u",
                "root",
                "-N",
                f"--socket={MYSQLD_SOCK_FILE}",
                "-e",
                "script",
            ],
            timeout=None,
        )

        _container.reset_mock()
        self.mysql._run_mysqlcli_script(("script",), password="rootpassword")
        _container.exec.assert_called_once_with(
            [
                "/usr/bin/mysql",
                "-u",
                "root",
                "-p",
                "-N",
                f"--socket={MYSQLD_SOCK_FILE}",
                "-e",
                "script",
            ],
            timeout=None,
            stdin="rootpassword",
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

    @patch("ops.model.Container")
    def test_log_rotate_config(self, _container):
        """Test log_rotate_config."""
        rendered_logrotate_config = (
            "# Use system user\nsu mysql mysql\n\n# Create dedicated subdirectory for rotated "
            "files\ncreateolddir 770 mysql mysql\n\n# Frequency of logs rotation\nhourly\nmaxa"
            "ge 1\nrotate 1440\n\n# Compression settings\n\nnocompress\n\n\n# Naming of rotate"
            "d files should be in the format:\ndateext\ndateformat -%Y%m%d_%H%M\n\n# Settings "
            "to prevent misconfigurations and unwanted behaviours\nifempty\nmissingok\nnomail\n"
            "nosharedscripts\nnocopytruncate\n\n\n/var/log/mysql/error.log {\n    olddir archi"
            "ve_error\n}\n\n/var/log/mysql/general.log {\n    olddir archive_general\n}\n\n/va"
            "r/log/mysql/slowquery.log {\n    olddir archive_slowquery\n}\n\n/var/log/mysql/au"
            "dit.log {\n    olddir archive_audit\n}\n\n"
        )

        self.mysql.container = _container
        self.mysql.setup_logrotate_config(1, ["error", "general", "slowquery", "audit"], False)

        self.mysql.container.push.assert_called_once_with(
            "/etc/logrotate.d/flush_mysql_logs",
            rendered_logrotate_config,
            permissions=416,
            user="root",
            group="root",
        )

    def test_update_endpoints(self):
        """Test the successful execution of update_endpoints."""
        _label_pod = MagicMock()
        _mock_k8s_helper = MagicMock()
        _mock_k8s_helper.label_pod = _label_pod

        _mock_charm = MagicMock()
        _mock_charm.get_cluster_endpoints.return_value = (
            "mysql-0.mysql-endpoints",
            "mysql-1.mysql-endpoints,mysql-2.mysql-endpoints",
            "mysql-3.mysql-endpoints",
        )

        self.mysql.k8s_helper = _mock_k8s_helper
        self.mysql.charm = _mock_charm

        calls = [
            call("primary", "mysql-0"),
            call("replicas", "mysql-1"),
            call("replicas", "mysql-2"),
            call("offline", "mysql-3"),
        ]

        self.mysql.update_endpoints(PEER)
        self.mysql.charm.get_cluster_endpoints.assert_called_once()

        _label_pod.assert_has_calls(calls)

    @patch("ops.model.Container")
    @patch("mysql_k8s_helpers.MySQL.wait_until_mysql_connection")
    def test_reset_root_password_and_start_mysqld(self, _wait_until_mysql_connection, _container):
        """Test for reset_root_password_and_start_mysqld()."""
        self.mysql.container = _container
        self.mysql.reset_root_password_and_start_mysqld()

        self.mysql.container.push.assert_has_calls([
            call(
                "/alter-root-user.sql",
                "ALTER USER 'root'@'localhost' IDENTIFIED BY 'password';\nFLUSH PRIVILEGES;",
                encoding="utf-8",
                permissions=384,
                user="mysql",
                group="mysql",
            ),
            call(
                "/etc/mysql/mysql.conf.d/z-custom-init-file.cnf",
                "[mysqld]\ninit_file = /alter-root-user.sql",
                encoding="utf-8",
                permissions=384,
                user="mysql",
                group="mysql",
            ),
        ])
        self.mysql.container.restart.assert_called_once_with("mysqld")
        _wait_until_mysql_connection.assert_called_once_with(check_port=False)
        self.mysql.container.remove_path.assert_has_calls([
            call("/alter-root-user.sql"),
            call("/etc/mysql/mysql.conf.d/z-custom-init-file.cnf"),
        ])

    @patch("ops.model.Container")
    @patch("mysql_k8s_helpers.MySQL.wait_until_mysql_connection")
    def test_reset_root_password_and_start_mysqld_error(
        self, _wait_until_mysql_connection, _container
    ):
        """Test exceptions in reset_root_password_and_start_mysqld()."""
        self.mysql.container = _container
        _container.push.side_effect = [
            None,
            PathError("not-found", "Should be a pebble exception"),
        ]

        with self.assertRaises(PathError):
            self.mysql.reset_root_password_and_start_mysqld()

        self.mysql.container.push.assert_has_calls([
            call(
                "/alter-root-user.sql",
                "ALTER USER 'root'@'localhost' IDENTIFIED BY 'password';\nFLUSH PRIVILEGES;",
                encoding="utf-8",
                permissions=384,
                user="mysql",
                group="mysql",
            ),
        ])
        self.mysql.container.remove_path.assert_called_once_with("/alter-root-user.sql")
        _wait_until_mysql_connection.assert_not_called()

        _container.push.side_effect = [None, None]
        _container.push.reset_mock()
        _container.remove_path.reset_mock()

        _wait_until_mysql_connection.side_effect = [
            MySQLServiceNotRunningError("mysqld not running")
        ]

        with self.assertRaises(MySQLServiceNotRunningError):
            self.mysql.reset_root_password_and_start_mysqld()

        self.mysql.container.push.assert_has_calls([
            call(
                "/alter-root-user.sql",
                "ALTER USER 'root'@'localhost' IDENTIFIED BY 'password';\nFLUSH PRIVILEGES;",
                encoding="utf-8",
                permissions=384,
                user="mysql",
                group="mysql",
            ),
            call(
                "/etc/mysql/mysql.conf.d/z-custom-init-file.cnf",
                "[mysqld]\ninit_file = /alter-root-user.sql",
                encoding="utf-8",
                permissions=384,
                user="mysql",
                group="mysql",
            ),
        ])
        self.mysql.container.restart.assert_called_once_with("mysqld")
        self.mysql.container.remove_path.assert_has_calls([
            call("/alter-root-user.sql"),
            call("/etc/mysql/mysql.conf.d/z-custom-init-file.cnf"),
        ])
