# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import MySQLOperatorCharm
from constants import PASSWORD_LENGTH
from mysql_k8s_helpers import MySQL, MySQLInitialiseMySQLDError

APP_NAME = "mysql-k8s"


class TestCharm(unittest.TestCase):
    def setUp(self) -> None:
        self.patcher = patch("lightkube.core.client.GenericSyncClient")
        self.patcher.start()
        self.harness = Harness(MySQLOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.peer_relation_id = self.harness.add_relation("database-peers", "database-peers")
        self.harness.add_relation_unit(self.peer_relation_id, f"{APP_NAME}/1")
        self.charm = self.harness.charm
        self.layer_dict = {
            "summary": "mysqld safe layer",
            "description": "pebble config layer for mysqld safe",
            "services": {
                "mysqld_safe": {
                    "override": "replace",
                    "summary": "mysqld safe",
                    "command": "mysqld_safe",
                    "startup": "enabled",
                    "user": "mysql",
                    "group": "mysql",
                }
            },
        }

    def tearDown(self) -> None:
        self.patcher.stop()

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

    @patch("mysql_k8s_helpers.MySQL.safe_stop_mysqld_safe")
    @patch("mysql_k8s_helpers.MySQL.get_mysql_version", return_value="8.0.0")
    @patch("mysql_k8s_helpers.MySQL.wait_until_mysql_connection")
    @patch("mysql_k8s_helpers.MySQL.configure_mysql_users")
    @patch("mysql_k8s_helpers.MySQL.configure_instance")
    @patch("mysql_k8s_helpers.MySQL.create_cluster")
    @patch("mysql_k8s_helpers.MySQL.create_custom_config_file")
    @patch("mysql_k8s_helpers.MySQL.initialise_mysqld")
    @patch("mysql_k8s_helpers.MySQL.is_instance_in_cluster")
    @patch("mysql_k8s_helpers.MySQL.get_member_state", return_value=("online", "primary"))
    @patch(
        "mysql_k8s_helpers.MySQL.get_innodb_buffer_pool_parameters", return_value=(123456, None)
    )
    def test_mysql_pebble_ready(
        self,
        _get_innodb_buffer_pool_parameters,
        _get_member_state,
        _is_instance_in_cluster,
        _initialise_mysqld,
        _create_custom_config_file,
        _create_cluster,
        _configure_instance,
        _configure_mysql_users,
        _wait_until_mysql_connection,
        _get_mysql_version,
        _safe_stop_mysqld_safe,
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

        _safe_stop_mysqld_safe.assert_called_once()

    @patch("charm.MySQLOperatorCharm._mysql", new_callable=PropertyMock)
    def test_mysql_pebble_ready_non_leader(self, _mysql_mock):
        # Test pebble ready when not leader
        # Expect unit to be in waiting status
        self.harness.update_relation_data(
            self.peer_relation_id, f"{APP_NAME}/1", {"configured": "True"}
        )

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
        _mysql_mock.get_innodb_buffer_pool_parameters.return_value = (123456, None)
        _mysql_mock.initialise_mysqld.side_effect = MySQLInitialiseMySQLDError
        # Trigger pebble ready after leader election
        self.harness.container_pebble_ready("mysql")

        self.assertTrue(isinstance(self.charm.unit.status, BlockedStatus))

    def test_on_config_changed(self):
        # Test config changed set of cluster name
        self.assertEqual(self.charm.peers.data[self.charm.app].get("cluster-name"), None)
        self.harness.set_leader()
        self.charm.on.config_changed.emit()
        # Cluster name is `cluster-<hash>`
        self.assertNotEqual(
            self.charm.peers.data[self.charm.app]["cluster-name"], "not_valid_cluster_name"
        )

    def test_mysql_property(self):
        # Test mysql property instance of mysql_k8s_helpers.MySQL
        # set leader and populate peer relation data
        self.harness.set_leader()
        self.charm.on.config_changed.emit()
        self.harness.update_relation_data(
            self.peer_relation_id,
            f"{APP_NAME}/1",
            {
                "cluster-name": "cluster-1",
                "root-password": "root-password",
                "server-config-password": "server-config-password",
                "cluster-admin-password": "cluster-admin-password",
            },
        )

        mysql = self.charm._mysql
        self.assertTrue(isinstance(mysql, MySQL))

    @patch("charm.MySQLOperatorCharm._mysql")
    def test_on_peer_relation_joined(self, _mysql_mock):
        # Test basic peer relation joined calls
        self.harness.set_leader()
        event = MagicMock()
        event.unit.name.return_value = f"{APP_NAME}/2"
        self.charm._mysql = _mysql_mock

        _mysql_mock.is_instance_configured_for_innodb.return_value = True

        self.charm._on_peer_relation_joined(event)

        _mysql_mock.add_instance_to_cluster.called_once_with("mysql-k8s-endpoints.mysql-k8s-2")
        _mysql_mock.is_instance_configured_for_innodb.called_once_with(
            "mysql-k8s-endpoints.mysql-k8s-2"
        )

    # @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MySQLOperatorCharm._on_leader_elected")
    def test_get_secret(self, _):
        self.harness.set_leader()

        # Test application scope.
        assert self.charm.get_secret("app", "password") is None
        self.harness.update_relation_data(
            self.peer_relation_id, self.charm.app.name, {"password": "test-password"}
        )
        assert self.charm.get_secret("app", "password") == "test-password"

        # Test unit scope.
        assert self.charm.get_secret("unit", "password") is None
        self.harness.update_relation_data(
            self.peer_relation_id, self.charm.unit.name, {"password": "test-password"}
        )
        assert self.charm.get_secret("unit", "password") == "test-password"

    # @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MySQLOperatorCharm._on_leader_elected")
    def test_set_secret(self, _):
        self.harness.set_leader()

        # Test application scope.
        assert "password" not in self.harness.get_relation_data(
            self.peer_relation_id, self.charm.app.name
        )
        self.charm.set_secret("app", "password", "test-password")
        assert (
            self.harness.get_relation_data(self.peer_relation_id, self.charm.app.name)["password"]
            == "test-password"
        )

        # Test unit scope.
        assert "password" not in self.harness.get_relation_data(
            self.peer_relation_id, self.charm.unit.name
        )
        self.charm.set_secret("unit", "password", "test-password")
        assert (
            self.harness.get_relation_data(self.peer_relation_id, self.charm.unit.name)["password"]
            == "test-password"
        )
