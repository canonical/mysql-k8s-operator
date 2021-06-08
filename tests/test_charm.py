# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest

# import ipdb

from ops.testing import Harness
from ops.model import (
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

    def test_env_config(self):
        self.harness.set_leader(True)
        config_1 = {
            "MYSQL_ROOT_PASSWORD": "D10S",
            "MYSQL_USER": "DiegoArmando",
            "MYSQL_PASSWORD": "SegurolaYHabana",
            "MYSQL_DATABASE": "db_10",
        }
        relation_id = self.harness.add_relation("mysql", "mysql")
        self.harness.add_relation_unit(relation_id, "mysql/1")
        self.harness.update_config(config_1)
        self.assertEqual(
            self.harness.charm.env_config["MYSQL_ROOT_PASSWORD"], "D10S"
        )
        self.assertEqual(
            self.harness.charm.env_config["MYSQL_USER"], "DiegoArmando"
        )
        self.assertEqual(
            self.harness.charm.env_config["MYSQL_PASSWORD"], "SegurolaYHabana"
        )
        self.assertEqual(
            self.harness.charm.env_config["MYSQL_DATABASE"], "db_10"
        )

    def test_generate_random_root_password(self):
        self.harness.set_leader(True)
        config_2 = {
            "MYSQL_ROOT_PASSWORD": "",
        }
        relation_id = self.harness.add_relation("mysql", "mysql")
        self.harness.add_relation_unit(relation_id, "mysql/1")
        self.harness.update_config(config_2)
        self.assertEqual(
            len(self.harness.charm.env_config["MYSQL_ROOT_PASSWORD"]), 20
        )

    def test_default_configs(self):
        config = self.harness.model.config
        self.assertEqual(config["port"], 3306)
        self.assertTrue("MYSQL_ROOT_PASSWORD" in config)
        self.assertEqual(config["MYSQL_ROOT_PASSWORD"], "")

    def test_root_password_sent_via_config(self):
        self.harness.set_leader(True)
        config = {
            "MYSQL_ROOT_PASSWORD": "Diego!",
        }
        relation_id = self.harness.add_relation("mysql", "mysql")
        self.harness.add_relation_unit(relation_id, "mysql/1")
        self.harness.update_config(config)
        self.assertIn("MYSQL_ROOT_PASSWORD", self.harness.charm.env_config)

    def test__on_config_changed(self):
        self.harness.set_leader(True)
        config = {
            "MYSQL_ROOT_PASSWORD": "Diego!",
        }
        relation_id = self.harness.add_relation("mysql", "mysql")
        self.harness.add_relation_unit(relation_id, "mysql/1")
        self.harness.update_config(config)
        self.assertIn(
            "MYSQL_ROOT_PASSWORD", self.harness.charm._stored.mysql_setup
        )

    @patch("charm.MySQLCharm.unit_ip")
    def test__update_status_unit_is_leader_mysql_is_ready(self, mock_unit_ip):
        mock_unit_ip.return_value = "10.0.0.1"

        with patch("mysqlserver.MySQL.is_ready") as mock_is_ready:
            mock_is_ready.return_value = False
            self.harness.set_leader(True)
            config = {
                "MYSQL_ROOT_PASSWORD": "D10S!",
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
            "MYSQL_ROOT_PASSWORD": "D10S!",
        }
        relation_id = self.harness.add_relation("mysql", "mysql")
        self.harness.add_relation_unit(relation_id, "mysql/1")
        self.harness.update_config(config)
        self.harness.charm.on.update_status.emit()
        self.assertEqual(type(self.harness.charm.unit.status), WaitingStatus)
        self.assertEqual(
            self.harness.charm.unit.status.message, "MySQL not initialized"
        )
