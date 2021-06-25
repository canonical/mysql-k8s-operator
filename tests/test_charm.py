# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest

# import ipdb

from ops.testing import Harness
from ops.model import (
    ActiveStatus,
    WaitingStatus,
)
from charm import MySQLCharm
from unittest.mock import patch


class TestCharm(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Harness(MySQLCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.harness.add_oci_resource("mysql-image")

    def test_pebble_layer_is_dict(self):
        self.harness.set_leader(True)
        config = {}
        relation_id = self.harness.add_relation("mysql", "mysql")
        self.harness.add_relation_unit(relation_id, "mysql/1")
        self.harness.update_config(config)
        layer = self.harness.charm._build_pebble_layer()
        self.assertIsInstance(layer["services"]["mysql"], dict)

    def test_pebble_layer_has_random_root_password(self):
        self.harness.set_leader(True)
        config = {}
        relation_id = self.harness.add_relation("mysql", "mysql")
        self.harness.add_relation_unit(relation_id, "mysql/1")
        self.harness.update_config(config)
        env = self.harness.charm._build_pebble_layer()["services"]["mysql"][
            "environment"
        ]
        self.assertEqual(len(env["MYSQL_ROOT_PASSWORD"]), 20)

    def test_pebble_layer_with_custom_config(self):
        self.harness.set_leader(True)
        config = {
            "mysql_root_password": "D10S",
            "mysql_user": "DiegoArmando",
            "mysql_password": "SegurolaYHabana",
            "mysql_database": "db_10",
        }
        relation_id = self.harness.add_relation("mysql", "mysql")
        self.harness.add_relation_unit(relation_id, "mysql/1")
        self.harness.update_config(config)
        env = self.harness.charm._build_pebble_layer()["services"]["mysql"][
            "environment"
        ]
        self.assertEqual(
            env["MYSQL_ROOT_PASSWORD"], config["mysql_root_password"]
        )
        self.assertEqual(env["MYSQL_USER"], config["mysql_user"])
        self.assertEqual(env["MYSQL_PASSWORD"], config["mysql_password"])
        self.assertEqual(env["MYSQL_DATABASE"], config["mysql_database"])

    def test_default_configs(self):
        config = self.harness.model.config
        self.assertEqual(config["port"], 3306)
        self.assertTrue("mysql_root_password" in config)
        self.assertEqual(config["mysql_root_password"], "")

    def test__on_config_changed_is_leader(self):
        self.harness.set_leader(True)
        config = {
            "mysql_root_password": "Diego!",
        }
        relation_id = self.harness.add_relation("mysql", "mysql")
        self.harness.add_relation_unit(relation_id, "mysql/1")
        self.harness.update_config(config)
        peers_data = self.harness.charm.model.get_relation("mysql").data[
            self.harness.charm.app
        ]
        self.assertIn("mysql_root_password", peers_data)

    def test__on_config_changed_is_not_leader(self):
        self.harness.set_leader(False)
        config = {
            "mysql_root_password": "Diego!",
        }
        relation_id = self.harness.add_relation("mysql", "mysql")
        self.harness.add_relation_unit(relation_id, "mysql/1")
        self.harness.update_config(config)
        peers_data = self.harness.charm.model.get_relation("mysql").data[
            self.harness.charm.app
        ]
        self.assertNotIn("mysql_root_password", peers_data)

    @patch("charm.MySQLCharm.unit_ip")
    def test__update_status_unit_is_leader_mysql_is_not_ready(
        self, mock_unit_ip
    ):
        mock_unit_ip.return_value = "10.0.0.1"

        with patch("mysqlserver.MySQL.is_ready") as mock_is_ready:
            mock_is_ready.return_value = False
            self.harness.set_leader(True)
            config = {
                "mysql_root_password": "D10S!",
            }
            relation_id = self.harness.add_relation("mysql", "mysql")
            self.harness.add_relation_unit(relation_id, "mysql/1")
            self.harness.update_config(config)
            self.assertEqual(self.harness.charm.on.update_status.emit(), None)
            self.assertEqual(
                type(self.harness.charm.unit.status), WaitingStatus
            )
            self.assertEqual(
                self.harness.charm.unit.status.message, "MySQL not ready yet"
            )

    @patch("charm.MySQLCharm._is_mysql_initialized")
    @patch("mysqlserver.MySQL.is_ready")
    @patch("charm.MySQLCharm.unit_ip")
    def test__update_status_unit_is_leader_mysql_not_initialized(
        self, mock_unit_ip, mock_is_ready, mock_is_mysql_initialized
    ):
        mock_unit_ip.return_value = "10.0.0.1"
        mock_is_ready.return_value = True
        mock_is_mysql_initialized.return_value = False

        self.harness.set_leader(True)
        config = {
            "mysql_root_password": "D10S!",
        }
        relation_id = self.harness.add_relation("mysql", "mysql")
        self.harness.add_relation_unit(relation_id, "mysql/1")
        self.harness.update_config(config)
        self.harness.charm.on.update_status.emit()
        self.assertEqual(type(self.harness.charm.unit.status), WaitingStatus)
        self.assertEqual(
            self.harness.charm.unit.status.message, "MySQL not initialized"
        )

    @patch("charm.MySQLCharm._is_mysql_initialized")
    @patch("mysqlserver.MySQL.is_ready")
    @patch("charm.MySQLCharm.unit_ip")
    def test__update_status_unit_is_leader_mysql_initialized(
        self, mock_unit_ip, mock_is_ready, mock_is_mysql_initialized
    ):
        mock_unit_ip.return_value = "10.0.0.1"
        mock_is_ready.return_value = True
        mock_is_mysql_initialized.return_value = True

        self.harness.set_leader(True)
        config = {
            "mysql_root_password": "D10S!",
        }
        relation_id = self.harness.add_relation("mysql", "mysql")
        self.harness.add_relation_unit(relation_id, "mysql/1")
        self.harness.update_config(config)
        self.harness.charm.on.update_status.emit()
        self.assertEqual(type(self.harness.charm.unit.status), ActiveStatus)

    def test__restart_service_model_error(self):
        self.harness.set_leader(True)

        with self.assertLogs(level="DEBUG") as logger:
            self.harness.charm._restart_service()
            self.assertEqual(
                sorted(logger.output),
                ["DEBUG:charm:MySQL service is not yet ready"],
            )
