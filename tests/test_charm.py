# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest

from ops.testing import Harness
from charm import MySQLCharm


class TestCharm(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Harness(MySQLCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.harness.add_oci_resource("mysql-image")

    def test_hostname_for_leader_unit(self):
        self.harness.set_leader(True)
        expected_host = "mysql-0.mysql-endpoints"
        self.assertEqual(self.harness.charm.hostname, expected_host)

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

    def test_get_unit_number_from_unit_name(self):
        unit_number = self.harness.charm._get_unit_number_from_unit_name(
            "mysql-3.mysql.endpoints"
        )
        self.assertEqual(unit_number, 3)

        unit_number2 = self.harness.charm._get_unit_number_from_unit_name(
            "mysql-x.mysql.endpoints"
        )
        self.assertEqual(unit_number2, None)

    def test_hostname(self):
        hostname1 = self.harness.charm._get_unit_hostname(10)
        self.assertEqual(hostname1, "mysql-10.mysql-endpoints")

        unit1 = self.harness.charm._get_unit_number_from_hostname(hostname1)
        self.assertEqual(unit1, 10)

        hostname2 = "mysql-8.mysql-endpoints"
        unit2 = self.harness.charm._get_unit_number_from_hostname(hostname2)
        self.assertEqual(unit2, 8)

        hostname3 = "mysql-x.mysql-endpoints"
        unit3 = self.harness.charm._get_unit_number_from_hostname(hostname3)
        self.assertEqual(unit3, None)
