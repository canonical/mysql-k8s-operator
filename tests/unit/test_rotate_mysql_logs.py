# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

from charms.mysql.v0.mysql import MySQLClientError, MySQLExecError
from ops.testing import Harness

from charm import MySQLOperatorCharm
from constants import CONTAINER_NAME


class TestRotateMySQLLogs(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(MySQLOperatorCharm)
        self.harness.begin()
        self.rotate_mysql_logs = self.harness.charm.rotate_mysql_logs

    @patch("charm.MySQLOperatorCharm._mysql")
    @patch("mysql_k8s_helpers.MySQL._execute_commands")
    @patch("mysql_k8s_helpers.MySQL.flush_mysql_logs")
    def test_skip_log_rotation(self, mock_flush, mock_exec, mock_mysql):
        mock_mysql._execute_commands = mock_exec
        mock_mysql.flush_mysql_logs = mock_flush
        # 1/3 skip if not peer relation
        self.rotate_mysql_logs._rotate_mysql_logs(None)
        mock_flush.assert_not_called()
        mock_exec.assert_not_called()

        # 2/3 set peer relation
        self.peer_relation_id = self.harness.add_relation("database-peers", "database-peers")
        self.rotate_mysql_logs._rotate_mysql_logs(None)
        mock_flush.assert_not_called()
        mock_exec.assert_not_called()

        # 3/3 set unit init flag
        self.harness.update_relation_data(
            self.peer_relation_id, self.harness.charm.unit.name, {"unit-initialized": "True"}
        )
        self.rotate_mysql_logs._rotate_mysql_logs(None)
        mock_flush.assert_not_called()
        mock_exec.assert_not_called()

    @patch("charm.MySQLOperatorCharm._mysql")
    @patch("mysql_k8s_helpers.MySQL._execute_commands")
    @patch("mysql_k8s_helpers.MySQL.flush_mysql_logs")
    def test_exec_log_rotation(self, mock_flush, mock_exec, mock_mysql):
        mock_mysql._execute_commands = mock_exec
        mock_mysql.flush_mysql_logs = mock_flush
        self.peer_relation_id = self.harness.add_relation("database-peers", "database-peers")

        self.harness.update_relation_data(
            self.peer_relation_id, self.harness.charm.unit.name, {"unit-initialized": "True"}
        )
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.rotate_mysql_logs._rotate_mysql_logs(None)
        mock_flush.assert_called_once()
        mock_exec.assert_called_once()

    @patch("charm.MySQLOperatorCharm._mysql")
    @patch("mysql_k8s_helpers.MySQL._execute_commands")
    @patch("mysql_k8s_helpers.MySQL.flush_mysql_logs")
    def test_log_rotation_exceptions(self, mock_flush, mock_exec, mock_mysql):
        mock_mysql._execute_commands = mock_exec
        mock_mysql.flush_mysql_logs = mock_flush
        self.peer_relation_id = self.harness.add_relation("database-peers", "database-peers")

        self.harness.update_relation_data(
            self.peer_relation_id, self.harness.charm.unit.name, {"unit-initialized": "True"}
        )
        self.harness.container_pebble_ready(CONTAINER_NAME)

        mock_exec.side_effect = MySQLExecError("Error")

        self.rotate_mysql_logs._rotate_mysql_logs(None)
        mock_exec.assert_called_once()
        mock_flush.assert_not_called()

        mock_exec.side_effect = None
        mock_exec.reset_mock()
        mock_flush.side_effect = MySQLClientError("Error")
        self.rotate_mysql_logs._rotate_mysql_logs(None)
        mock_flush.assert_called_once()
        mock_exec.assert_called_once()
