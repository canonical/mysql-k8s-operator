# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest
from unittest.mock import PropertyMock, patch

import pytest
from ops.model import ActiveStatus, WaitingStatus
from ops.testing import Harness

from charm import MySQLOperatorCharm
from constants import (
    BACKUPS_PASSWORD_KEY,
    CLUSTER_ADMIN_PASSWORD_KEY,
    MONITORING_PASSWORD_KEY,
    PASSWORD_LENGTH,
    ROOT_PASSWORD_KEY,
    SERVER_CONFIG_PASSWORD_KEY,
)
from mysql_k8s_helpers import MySQL, MySQLInitialiseMySQLDError

APP_NAME = "mysql-k8s"
REQUIRED_PASSWORD_KEYS = [
    ROOT_PASSWORD_KEY,
    MONITORING_PASSWORD_KEY,
    CLUSTER_ADMIN_PASSWORD_KEY,
    SERVER_CONFIG_PASSWORD_KEY,
    BACKUPS_PASSWORD_KEY,
]


class TestCharm(unittest.TestCase):
    def setUp(self) -> None:
        self.patcher = patch("lightkube.core.client.GenericSyncClient")
        self.patcher.start()
        self.harness = Harness(MySQLOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.peer_relation_id = self.harness.add_relation("database-peers", "database-peers")
        self.restart_relation_id = self.harness.add_relation("restart", "restart")
        self.harness.add_relation_unit(self.peer_relation_id, f"{APP_NAME}/1")
        self.charm = self.harness.charm
        self.maxDiff = None

    @pytest.fixture
    def use_caplog(self, caplog):
        self._caplog = caplog

    def layer_dict(self, with_mysqld_exporter: bool = False):
        return {
            "summary": "mysqld services layer",
            "description": "pebble config layer for mysqld safe and exporter",
            "services": {
                "mysqld_safe": {
                    "override": "replace",
                    "summary": "mysqld safe",
                    "command": "mysqld_safe",
                    "startup": "enabled",
                    "user": "mysql",
                    "group": "mysql",
                    "kill-delay": "24h",
                },
                "mysqld_exporter": {
                    "override": "replace",
                    "summary": "mysqld exporter",
                    "command": "/start-mysqld-exporter.sh",
                    "startup": "enabled" if with_mysqld_exporter else "disabled",
                    "user": "mysql",
                    "group": "mysql",
                    "environment": {
                        "EXPORTER_USER": "monitoring",
                        "EXPORTER_PASS": self.charm.get_secret('app', 'monitoring-password'),
                    },
                },
            },
        }

    def tearDown(self) -> None:
        self.patcher.stop()

    def test_mysqld_layer(self):
        # Test layer property
        # Comparing output dicts
        self.assertEqual(self.charm._pebble_layer.to_dict(), self.layer_dict())

    @pytest.mark.usefixtures("without_juju_secrets")
    def test_on_leader_elected(self):
        # Test leader election setting of
        # peer relation data
        self.harness.set_leader()
        peer_data = self.harness.get_relation_data(self.peer_relation_id, self.charm.app)
        # Test passwords in content and length
        for password in REQUIRED_PASSWORD_KEYS:
            self.assertTrue(
                peer_data[password].isalnum() and len(peer_data[password]) == PASSWORD_LENGTH
            )

    def test_on_leader_elected_secrets(self):
        # Test leader election setting of secret data
        self.harness.set_leader()

        # > 3.1.7 changed way last revision secret is accessed (peek)
        secret_data = self.harness.model.get_secret(
            label="database-peers.mysql-k8s.app"
        ).peek_content()

        # Test passwords in content and length
        for password in REQUIRED_PASSWORD_KEYS:
            self.assertTrue(
                secret_data[password].isalnum() and len(secret_data[password]) == PASSWORD_LENGTH
            )

    @patch("mysql_k8s_helpers.MySQL.rescan_cluster")
    @patch("charms.mysql.v0.mysql.MySQLCharmBase.active_status_message", return_value="")
    @patch("upgrade.MySQLK8sUpgrade.idle", return_value=True)
    @patch("mysql_k8s_helpers.MySQL.write_content_to_file")
    @patch("mysql_k8s_helpers.MySQL.is_data_dir_initialised", return_value=False)
    @patch("mysql_k8s_helpers.MySQL.create_cluster_set")
    @patch("mysql_k8s_helpers.MySQL.initialize_juju_units_operations_table")
    @patch("mysql_k8s_helpers.MySQL.get_mysql_version", return_value="8.0.0")
    @patch("mysql_k8s_helpers.MySQL.wait_until_mysql_connection")
    @patch("mysql_k8s_helpers.MySQL.configure_mysql_users")
    @patch("mysql_k8s_helpers.MySQL.configure_instance")
    @patch("mysql_k8s_helpers.MySQL.create_cluster")
    @patch("mysql_k8s_helpers.MySQL.initialise_mysqld")
    @patch("mysql_k8s_helpers.MySQL.fix_data_dir")
    @patch("mysql_k8s_helpers.MySQL.is_instance_in_cluster")
    @patch("mysql_k8s_helpers.MySQL.get_member_state", return_value=("online", "primary"))
    @patch(
        "mysql_k8s_helpers.MySQL.get_innodb_buffer_pool_parameters",
        return_value=(123456, None, None),
    )
    @patch("mysql_k8s_helpers.MySQL.get_max_connections", return_value=120)
    @patch("mysql_k8s_helpers.MySQL.setup_logrotate_config")
    def test_mysql_pebble_ready(
        self,
        _,
        _get_max_connections,
        _get_innodb_buffer_pool_parameters,
        _get_member_state,
        _is_instance_in_cluster,
        _initialise_mysqld,
        _fix_data_dir,
        _create_cluster,
        _configure_instance,
        _configure_mysql_users,
        _wait_until_mysql_connection,
        _get_mysql_version,
        _initialize_juju_units_operations_table,
        _is_data_dir_initialised,
        _create_cluster_set,
        _write_content_to_file,
        _active_status_message,
        _upgrade_idle,
        _rescan_cluster,
    ):
        # Check if initial plan is empty
        self.harness.set_can_connect("mysql", True)
        initial_plan = self.harness.get_container_pebble_plan("mysql")
        self.assertEqual(initial_plan.to_yaml(), "{}\n")

        # Trigger pebble ready before leader election
        self.harness.container_pebble_ready("mysql")
        self.assertTrue(isinstance(self.charm.unit.status, WaitingStatus))

        self.harness.set_leader()
        # Trigger pebble ready after leader election
        self.harness.container_pebble_ready("mysql")
        self.assertTrue(isinstance(self.charm.unit.status, ActiveStatus))

        # After configuration run, plan should be populated
        plan = self.harness.get_container_pebble_plan("mysql")
        self.assertEqual(
            plan.to_dict()["services"],  # pyright: ignore[reportTypedDictNotRequiredAccess]
            self.layer_dict()["services"],
        )

        self.harness.add_relation("metrics-endpoint", "test-cos-app")
        plan = self.harness.get_container_pebble_plan("mysql")
        self.assertEqual(
            plan.to_dict()["services"],  # pyright: ignore[reportTypedDictNotRequiredAccess]
            self.layer_dict(with_mysqld_exporter=True)["services"],
        )

    @patch("charm.MySQLOperatorCharm.join_unit_to_cluster")
    @patch("charm.MySQLOperatorCharm._configure_instance")
    @patch("charm.MySQLOperatorCharm._write_mysqld_configuration")
    @patch("upgrade.MySQLK8sUpgrade.idle", return_value=True)
    @patch("charm.MySQLOperatorCharm._mysql")
    def test_pebble_ready_set_data(
        self, mock_mysql, mock_upgrade_idle, mock_write_conf, mock_conf, mock_join
    ):
        mock_mysql.is_data_dir_initialised.return_value = False
        mock_mysql.get_member_state.return_value = ("online", "primary")
        self.harness.set_can_connect("mysql", True)
        self.harness.set_leader()

        # test on non leader
        self.harness.set_leader(is_leader=False)
        self.harness.container_pebble_ready("mysql")
        self.assertEqual(self.charm.unit_peer_data.get("unit-initialized"), None)
        self.assertEqual(self.charm.unit_peer_data["member-role"], "secondary")
        self.assertEqual(self.charm.unit_peer_data["member-state"], "waiting")

        # test on leader
        self.harness.set_leader(is_leader=True)
        self.harness.container_pebble_ready("mysql")
        self.assertEqual(self.charm.unit_peer_data["unit-initialized"], "True")
        self.assertEqual(self.charm.unit_peer_data["member-state"], "online")
        self.assertEqual(self.charm.unit_peer_data["member-role"], "primary")

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
        self.charm._mysql = _mysql_mock
        _mysql_mock.render_mysqld_configuration.return_value = ("content", {"config": "data"})
        _mysql_mock.get_innodb_buffer_pool_parameters.return_value = (123456, None, None)
        _mysql_mock.initialise_mysqld.side_effect = MySQLInitialiseMySQLDError
        # Trigger pebble ready after leader election
        self.harness.container_pebble_ready("mysql")

        self.assertFalse(isinstance(self.charm.unit.status, ActiveStatus))

    def test_on_config_changed(self):
        # Test config changed set of cluster name
        self.assertEqual(self.charm.peers.data[self.charm.app].get("cluster-name"), None)
        self.harness.set_leader()
        self.charm.on.config_changed.emit()
        # Cluster name is `cluster-<hash>`
        self.assertNotEqual(
            self.charm.peers.data[self.charm.app]["cluster-name"], "not_valid_cluster_name"
        )

    @patch("mysql_k8s_helpers.MySQL.is_data_dir_initialised", return_value=False)
    def test_mysql_property(self, _):
        # Test mysql property instance of mysql_k8s_helpers.MySQL
        # set leader and populate peer relation data
        self.harness.set_leader()
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

    @pytest.mark.usefixtures("without_juju_secrets")
    @patch("charm.MySQLOperatorCharm._on_leader_elected")
    def test_set_secret_databag(self, _):
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

    @patch("charms.mysql.v0.mysql.MySQLBase.is_cluster_replica", return_value=False)
    @patch("mysql_k8s_helpers.MySQL.remove_instance")
    @patch("mysql_k8s_helpers.MySQL.get_primary_label")
    @patch("mysql_k8s_helpers.MySQL.is_instance_in_cluster", return_value=True)
    def test_database_storage_detaching(
        self,
        mock_is_instance_in_cluster,
        mock_get_primary_label,
        mock_remove_instance,
        mock_is_cluster_replica,
    ):
        self.harness.update_relation_data(
            self.peer_relation_id, self.charm.unit.name, {"unit-initialized": "True"}
        )
        self.harness.update_relation_data(
            self.peer_relation_id,
            self.charm.app.name,
            {"cluster-name": "cluster-1", "cluster-set-domain-name": "cluster-1"},
        )
        mock_get_primary_label.return_value = self.charm.unit_label

        self.charm._on_database_storage_detaching(None)
        mock_remove_instance.assert_called_once_with(self.charm.unit_label, lock_instance=None)

        self.assertEqual(
            self.harness.get_relation_data(self.peer_relation_id, self.charm.unit.name)[
                "unit-status"
            ],
            "removing",
        )
