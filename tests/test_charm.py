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

    def test_env_config(self):
        config_1 = {
            "MYSQL_ROOT_PASSWORD": "D10S",
            "MYSQL_USER": "DiegoArmando",
            "MYSQL_PASSWORD": "SegurolaYHabana",
            "MYSQL_DATABASE": "db_10",
        }
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
        self.harness.update_config(config_2)
        self.assertEqual(
            len(self.harness.charm.env_config["MYSQL_ROOT_PASSWORD"]), 20
        )

    def test_status(self):
        config_1 = {
            "MYSQL_ROOT_PASSWORD": "D10S",
        }
        self.harness.set_leader(True)
        self.harness.update_config(config_1)
        self.assertEqual(
            self.harness.charm.unit.status,
            ActiveStatus(),
        )

    def test_default_configs(self):
        config = self.harness.model.config
        self.assertEqual(config["port"], 3306)
        self.assertTrue("MYSQL_ROOT_PASSWORD" in config)
        self.assertEqual(config["MYSQL_ROOT_PASSWORD"], "")

    def test_root_password_sent_via_config(self):
        self.harness.set_leader(False)
        config = {
            "MYSQL_ROOT_PASSWORD": "Diego!",
        }
        self.harness.update_config(config)
        self.assertIn(
            "mysql_root_password", self.harness.charm._stored.mysql_setup
        )

    def test__on_config_changed(self):
        self.harness.set_leader(True)
        config = {
            "MYSQL_ROOT_PASSWORD": "Diego!",
        }
        self.harness.update_config(config)
        self.assertIn(
            "mysql_root_password", self.harness.charm._stored.mysql_setup
        )

    def test_new_unit_has_password(self):
        config = {
            "MYSQL_ROOT_PASSWORD": "D10S!",
        }

        self.harness.update_config(config)
        relation_id = self.harness.add_relation("mysql", "mysql")
        self.harness.add_relation_unit(relation_id, "mysql/1")
        self.harness.update_relation_data(relation_id, "mysql", config)
        self.assertEqual(
            config["MYSQL_ROOT_PASSWORD"],
            self.harness.charm._stored.mysql_setup["mysql_root_password"],
        )

    @patch("charm.MySQLCharm.unit_ip")
    def test__on_start(self, mock_unit_ip):
        mock_unit_ip.return_value = "10.0.0.1"
        # Checking the _on_start method when the unit is not leader
        self.harness.set_leader(False)
        self.assertEqual(self.harness.charm.on.start.emit(), None)

        # Checking the _on_start method when the unit is leader
        # but MySQL isn't ready
        with patch("mysqlserver.MySQL.is_ready") as mock_is_ready:
            mock_is_ready.return_value = False
            self.harness.set_leader(True)
            config = {
                "MYSQL_ROOT_PASSWORD": "D10S!",
            }
            self.harness.update_config(config)
            self.assertEqual(self.harness.charm.on.start.emit(), None)

        # Checking the _on_start method when the unit is leader
        # and MySQL is ready
        with patch("mysqlserver.MySQL.is_ready") as mock_is_ready:
            self.harness.set_leader(True)
            mock_is_ready.return_value = True
            config = {
                "MYSQL_ROOT_PASSWORD": "D10S!",
            }
            self.harness.update_config(config)
            self.harness.charm.on.start.emit()
            self.assertEqual(
                type(self.harness.charm.unit.status), ActiveStatus
            )

    def test__update_status_unit_is_not_leader(self):
        self.harness.set_leader(False)
        self.assertEqual(self.harness.charm.on.update_status.emit(), None)
        self.assertEqual(type(self.harness.charm.unit.status), ActiveStatus)
        self.assertEqual(self.harness.charm.unit.status.message, "")

    @patch("charm.MySQLCharm.unit_ip")
    def test__update_status_unit_is_leader_mysql_is_ready(self, mock_unit_ip):
        mock_unit_ip.return_value = "10.0.0.1"

        with patch("mysqlserver.MySQL.is_ready") as mock_is_ready:
            mock_is_ready.return_value = False
            self.harness.set_leader(True)
            config = {
                "MYSQL_ROOT_PASSWORD": "D10S!",
            }
            self.harness.update_config(config)
            self.assertEqual(self.harness.charm.on.update_status.emit(), None)
            self.assertEqual(
                type(self.harness.charm.unit.status), WaitingStatus
            )
            self.assertEqual(
                self.harness.charm.unit.status.message, "MySQL not ready yet"
            )

    @patch("charm.MySQLCharm.unit_ip")
    def test__update_status_unit_is_leader_mysql_not_initialized(
        self, mock_unit_ip
    ):
        mock_unit_ip.return_value = "10.0.0.1"

        with patch("mysqlserver.MySQL.is_ready") as mock_is_ready:
            self.harness.set_leader(True)
            mock_is_ready.return_value = True
            config = {
                "MYSQL_ROOT_PASSWORD": "D10S!",
            }
            self.harness.update_config(config)
            self.harness.charm.on.update_status.emit()
            self.assertEqual(
                type(self.harness.charm.unit.status), WaitingStatus
            )
            self.assertEqual(
                self.harness.charm.unit.status.message, "MySQL not initialized"
            )
