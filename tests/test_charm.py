# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest

from ops.testing import Harness
from ops.model import (
    ActiveStatus,
)
from charm import MySQLCharm


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
        self.assertEqual(self.harness.charm.env_config["MYSQL_ROOT_PASSWORD"], "D10S")
        self.assertEqual(self.harness.charm.env_config["MYSQL_USER"], "DiegoArmando")
        self.assertEqual(
            self.harness.charm.env_config["MYSQL_PASSWORD"], "SegurolaYHabana"
        )
        self.assertEqual(self.harness.charm.env_config["MYSQL_DATABASE"], "db_10")

        config_2 = {
            "MYSQL_ROOT_PASSWORD": "",
        }
        self.harness.update_config(config_2)
        self.assertEqual(len(self.harness.charm.env_config["MYSQL_ROOT_PASSWORD"]), 20)

    def test_pod_spec(self):
        config_1 = {
            "MYSQL_ROOT_PASSWORD": "D10S",
        }
        self.harness.update_config(config_1)
        pod_spec = self.harness.charm._build_pod_spec()
        self.assertEqual(pod_spec["containers"][0]["name"], "mysql")
        self.assertEqual(pod_spec["containers"][0]["ports"][0]["containerPort"], 3306)
        self.assertEqual(pod_spec["containers"][0]["ports"][0]["protocol"], "TCP")
        self.assertEqual(
            pod_spec["containers"][0]["envConfig"]["MYSQL_ROOT_PASSWORD"], "D10S"
        )
        self.assertEqual(pod_spec["version"], 3)

    def test_status(self):
        config_1 = {
            "MYSQL_ROOT_PASSWORD": "D10S",
        }
        self.harness.set_leader(True)
        self.harness.update_config(config_1)
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())
