# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import call, patch

from charms.data_platform_libs.v0.upgrade import (
    ClusterNotReadyError,
    KubernetesClientError,
)
from charms.mysql.v0.mysql import MySQLSetClusterPrimaryError, MySQLSetVariableError
from ops.model import BlockedStatus
from ops.testing import Harness

import k8s_helpers
from charm import MySQLOperatorCharm

MOCK_STATUS_ONLINE = {
    "defaultreplicaset": {
        "topology": {
            "0": {"status": "online"},
            "1": {"status": "online"},
        },
    }
}
MOCK_STATUS_OFFLINE = {
    "defaultreplicaset": {
        "topology": {
            "0": {"status": "online"},
            "1": {"status": "online", "instanceerrors": ["some error"]},
        },
    }
}


class TestUpgrade(unittest.TestCase):
    """Test the upgrade class."""

    def setUp(self):
        """Set up the test."""
        self.patcher = patch("lightkube.core.client.GenericSyncClient")
        self.patcher.start()
        self.harness = Harness(MySQLOperatorCharm)
        self.harness.begin()
        self.upgrade_relation_id = self.harness.add_relation("upgrade", "mysql-k8s")
        self.peer_relation_id = self.harness.add_relation("database-peers", "mysql-k8s")
        for rel_id in (self.upgrade_relation_id, self.peer_relation_id):
            self.harness.add_relation_unit(rel_id, "mysql-k8s/1")
        self.harness.update_relation_data(
            self.upgrade_relation_id, "mysql-k8s/1", {"state": "idle"}
        )
        self.harness.update_relation_data(
            self.peer_relation_id,
            "mysql-k8s",
            {"cluster-name": "test_cluster", "cluster-set-domain-name": "test_cluster_set"},
        )
        self.charm = self.harness.charm

    def test_highest_ordinal(self):
        """Test the highest ordinal."""
        self.assertEqual(1, self.charm.upgrade.highest_ordinal)

    @patch("upgrade.MySQLK8sUpgrade._pre_upgrade_prepare")
    @patch("mysql_k8s_helpers.MySQL.get_cluster_status", return_value=MOCK_STATUS_ONLINE)
    def test_pre_upgrade_check(self, mock_get_cluster_status, mock_pre_upgrade_prepare):
        """Test the pre upgrade check."""
        self.harness.set_leader(True)
        self.charm.on.config_changed.emit()

        self.charm.upgrade.pre_upgrade_check()
        mock_pre_upgrade_prepare.assert_called_once()
        mock_get_cluster_status.assert_called_once()

        self.assertEqual(
            self.harness.get_relation_data(self.upgrade_relation_id, "mysql-k8s/0")["state"],
            "idle",
        )

        mock_get_cluster_status.return_value = MOCK_STATUS_OFFLINE

        with self.assertRaises(ClusterNotReadyError):
            self.charm.upgrade.pre_upgrade_check()

        mock_get_cluster_status.return_value = MOCK_STATUS_ONLINE

        mock_pre_upgrade_prepare.side_effect = MySQLSetClusterPrimaryError
        with self.assertRaises(ClusterNotReadyError):
            self.charm.upgrade.pre_upgrade_check()

        mock_pre_upgrade_prepare.side_effect = k8s_helpers.KubernetesClientError
        with self.assertRaises(ClusterNotReadyError):
            self.charm.upgrade.pre_upgrade_check()

        mock_pre_upgrade_prepare.side_effect = MySQLSetVariableError
        with self.assertRaises(ClusterNotReadyError):
            self.charm.upgrade.pre_upgrade_check()

    @patch("upgrade.logger.critical")
    def test_log_rollback(self, mock_logging):
        """Test roolback logging."""
        self.charm.upgrade.log_rollback_instructions()
        calls = [
            call(
                "Upgrade failed, follow the instructions below to rollback:\n"
                f"  1 - Run `juju refresh --revision <previous-revision> {self.charm.app.name}` to initiate the rollback\n"
                f"  2 - Run `juju run-action {self.charm.app.name}/leader resume-upgrade` to resume the rollback"
            ),
        ]
        mock_logging.assert_has_calls(calls)

    @patch("mysql_k8s_helpers.MySQL.set_dynamic_variable")
    @patch("mysql_k8s_helpers.MySQL.get_primary_label", return_value="mysql-k8s-1")
    @patch("mysql_k8s_helpers.MySQL.set_cluster_primary")
    @patch("k8s_helpers.KubernetesHelpers.set_rolling_update_partition")
    def test_pre_upgrade_prepare(
        self,
        mock_set_rolling_update_partition,
        mock_set_cluster_primary,
        mock_get_primary_label,
        mock_set_dynamic_variable,
    ):
        """Test the pre upgrade prepare."""
        self.harness.set_leader(True)
        self.charm.on.config_changed.emit()

        self.charm.upgrade._pre_upgrade_prepare()

        mock_set_cluster_primary.assert_called_once()
        mock_get_primary_label.assert_called_once()
        mock_set_rolling_update_partition.assert_called_once()
        assert mock_set_dynamic_variable.call_count == 2

    @patch("upgrade.RECOVER_ATTEMPTS", 1)
    @patch("mysql_k8s_helpers.MySQL.hold_if_recovering")
    @patch("mysql_k8s_helpers.MySQL.get_mysql_version", return_value="8.0.33")
    @patch("mysql_k8s_helpers.MySQL.verify_server_upgradable")
    @patch("mysql_k8s_helpers.MySQL.is_instance_in_cluster", return_value=True)
    def test_pebble_ready(
        self,
        mock_is_instance_in_cluster,
        mock_is_server_upgradable,
        mock_get_mysql_version,
        mock_hold_if_recovering,
    ):
        """Test the pebble ready."""
        self.charm.on.config_changed.emit()
        self.harness.update_relation_data(
            self.upgrade_relation_id, "mysql-k8s/0", {"state": "upgrading"}
        )
        self.charm.upgrade._on_pebble_ready(None)
        self.assertEqual(
            self.harness.get_relation_data(self.upgrade_relation_id, "mysql-k8s/1")["state"],
            "idle",  # change to `completed` - behavior not yet set in the lib
        )
        mock_is_instance_in_cluster.assert_called_once()

        self.harness.update_relation_data(
            self.upgrade_relation_id, "mysql-k8s/0", {"state": "upgrading"}
        )
        # setup for exception
        mock_is_instance_in_cluster.return_value = False

        self.charm.upgrade._on_pebble_ready(None)
        self.assertTrue(isinstance(self.charm.unit.status, BlockedStatus))

    @patch("k8s_helpers.KubernetesHelpers.set_rolling_update_partition")
    def test_set_rolling_update_partition(self, mock_set_rolling_update_partition):
        """Test the set rolling update partition."""
        self.charm.upgrade._set_rolling_update_partition(partition=1)
        mock_set_rolling_update_partition.assert_called_once()

        mock_set_rolling_update_partition.side_effect = k8s_helpers.KubernetesClientError
        with self.assertRaises(KubernetesClientError):
            self.charm.upgrade._set_rolling_update_partition(partition=1)

    @patch("mysql_k8s_helpers.MySQL.verify_server_upgradable")
    def test_check_server_upgradeability(self, mock_verify_server_upgradeable):
        """Test the server upgradeability check."""
        self.charm.upgrade._check_server_upgradeability()
        mock_verify_server_upgradeable.assert_not_called()

        self.charm.upgrade.upgrade_stack = [0, 1]

        self.charm.upgrade._check_server_upgradeability()
        mock_verify_server_upgradeable.assert_called_once()
