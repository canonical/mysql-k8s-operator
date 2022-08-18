# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import (
    CLUSTER_ADMIN_USERNAME,
    PASSWORD_LENGTH,
    SERVER_CONFIG_USERNAME,
    MySQLOperatorCharm,
)
from mysqlsh_helpers import MySQL, MySQLInitialiseMySQLDError

APP_NAME = "mysql-k8s"


class TestCharm(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Harness(MySQLOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.peer_relation_id = self.harness.add_relation("database-peers", "database-peers")
        self.harness.add_relation_unit(self.peer_relation_id, "mysql/1")
        self.charm = self.harness.charm
        self.layer_dict = {
            "summary": "mysqld layer",
            "description": "pebble config layer for mysqld",
            "services": {
                "mysqld": {
                    "override": "replace",
                    "summary": "mysqld",
                    "command": "mysqld",
                    "startup": "enabled",
                    "user": "mysql",
                    "group": "mysql",
                }
            },
        }

    def test_mysqld_layer(self):
        # Test layer property
        # Comparing output dicts
        self.assertEqual(self.charm._pebble_layer.to_dict(), self.layer_dict)

    def test_on_leader_elected(self):
        # Test leader election setting of
        # peer relation data
        self.harness.set_leader()
        peer_data = self.harness.get_relation_data(self.peer_relation_id, self.charm.app)
        # Test passwords in content and length
        required_passwords = ["root-password", "server-config-password", "cluster-admin-password"]
        for password in required_passwords:
            self.assertTrue(
                peer_data[password].isalnum() and len(peer_data[password]) == PASSWORD_LENGTH
            )

    @patch("mysqlsh_helpers.MySQL.get_mysql_version", return_value="8.0.0")
    @patch("mysqlsh_helpers.MySQL.wait_until_mysql_connection")
    @patch("mysqlsh_helpers.MySQL.configure_mysql_users")
    @patch("mysqlsh_helpers.MySQL.configure_instance")
    @patch("mysqlsh_helpers.MySQL.create_cluster")
    @patch("mysqlsh_helpers.MySQL.create_custom_config_file")
    @patch("mysqlsh_helpers.MySQL.initialise_mysqld")
    def test_mysql_pebble_ready(
        self,
        _initialise_mysqld,
        _create_custom_config_file,
        _create_cluster,
        _configure_instance,
        _configure_mysql_users,
        _wait_until_mysql_connection,
        _get_mysql_version,
    ):
        # Check if initial plan is empty
        self.harness.set_can_connect("mysql", True)
        initial_plan = self.harness.get_container_pebble_plan("mysql")
        self.assertEqual(initial_plan.to_yaml(), "{}\n")

        # Trigger pebble ready before leader election
        self.harness.container_pebble_ready("mysql")
        self.assertTrue(isinstance(self.charm.unit.status, WaitingStatus))

        self.harness.set_leader()
        self.charm.on.config_changed.emit()
        # Trigger pebble ready after leader election
        self.harness.container_pebble_ready("mysql")
        self.assertTrue(isinstance(self.charm.unit.status, ActiveStatus))

        # After configuration run, plan should be populated
        plan = self.harness.get_container_pebble_plan("mysql")
        self.assertEqual(plan.to_dict()["services"], self.layer_dict["services"])

    @patch("charm.MySQLOperatorCharm._mysql", new_callable=PropertyMock)
    def test_mysql_pebble_ready_non_leader(self, _mysql_mock):
        # Test pebble ready when not leader
        # Expect unit to be in waiting status
        self.harness.update_relation_data(self.peer_relation_id, "mysql/1", {"configured": "True"})

        _mysql_mock.get_mysql_version.return_value = "8.0.25"
        self.charm._mysql = _mysql_mock
        self.harness.container_pebble_ready("mysql")
        self.assertTrue(isinstance(self.charm.unit.status, WaitingStatus))

    @patch("charm.MySQLOperatorCharm._mysql")
    def test_mysql_pebble_ready_exception(self, _mysql_mock):
        # Test exception raised in bootstrapping
        self.harness.set_leader()
        self.charm.on.config_changed.emit()
        self.charm._mysql = _mysql_mock
        _mysql_mock.initialise_mysqld.side_effect = MySQLInitialiseMySQLDError
        # Trigger pebble ready after leader election
        self.harness.container_pebble_ready("mysql")

        self.assertTrue(isinstance(self.charm.unit.status, BlockedStatus))

    def test_on_config_changed(self):
        # Test config changed set of cluster name
        self.assertEqual(self.charm._peers.data[self.charm.app].get("cluster-name"), None)
        self.harness.set_leader()
        self.charm.on.config_changed.emit()
        # Cluster name is `cluster-<hash>`
        self.assertNotEqual(
            self.charm._peers.data[self.charm.app]["cluster-name"], "not_valid_cluster_name"
        )

    def test_mysql_property(self):
        # Test mysql property instance of mysqlsh_helpers.MySQL
        # set leader and populate peer relation data
        self.harness.set_leader()
        self.charm.on.config_changed.emit()
        self.harness.update_relation_data(
            self.peer_relation_id,
            "mysql/1",
            {
                "cluster-name": "cluster-1",
                "root-password": "root-password",
                "server-config-password": "server-config-password",
                "cluster-admin-password": "cluster-admin-password",
            },
        )

        mysql = self.charm._mysql
        self.assertTrue(isinstance(mysql, MySQL))

    def test_on_get_cluster_admin_credentials(self):
        # Test get generated passwords function
        # used as action
        self.harness.set_leader()
        event = MagicMock()
        self.charm._on_get_cluster_admin_credentials(event)

        event.set_results.assert_called_with(
            {
                "cluster-admin-username": CLUSTER_ADMIN_USERNAME,
                "cluster-admin-password": self.charm._peers.data[self.charm.app][
                    "cluster-admin-password"
                ],
            }
        )

    def test_on_get_server_config_credentials(self):
        # Test get generated passwords function
        # used as action
        self.harness.set_leader()
        event = MagicMock()
        self.charm._on_get_server_config_credentials(event)

        event.set_results.assert_called_with(
            {
                "server-config-username": SERVER_CONFIG_USERNAME,
                "server-config-password": self.charm._peers.data[self.charm.app][
                    "server-config-password"
                ],
            }
        )

    @patch("charm.MySQLOperatorCharm._mysql")
    def test_on_peer_relation_joined(self, _mysql_mock):
        # Test basic peer relation joined calls
        self.harness.set_leader()
        event = MagicMock()
        event.unit.name.return_value = "mysql/2"
        self.charm._mysql = _mysql_mock

        _mysql_mock.is_instance_configured_for_innodb.return_value = True

        self.charm._on_peer_relation_joined(event)

        _mysql_mock.add_instance_to_cluster.called_once_with("mysql-k8s-endpoints.mysql-2")
        _mysql_mock.is_instance_configured_for_innodb.called_once_with(
            "mysql-k8s-endpoints.mysql-2"
        )
