# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest

from mysqlserver import MySQL
from unittest.mock import patch
from types import SimpleNamespace
from mysql.connector import Error


class TestMySQLServer(unittest.TestCase):
    def setUp(self) -> None:
        mysql_config = {
            "app_name": "mysql",
            "host": "localhost",
            "port": 3306,
            "user_name": "root",
            "mysql_root_password": "D10S!",
        }
        self.mysql = MySQL(mysql_config)

    @patch("mysqlserver.MySQL._get_client")
    def test_is_ready(self, mock_get_client):
        mock_get_client.return_value = SimpleNamespace(close=lambda: True)
        self.assertTrue(self.mysql.is_ready())

        mock_get_client.side_effect = Error
        self.assertFalse(self.mysql.is_ready())

    @patch("mysqlserver.MySQL._get_client")
    def test_databases(self, mock_get_client):
        mock_get_client.return_value = SimpleNamespace(close=lambda: True)
        with patch(
            "mysqlserver.MySQL._databases_names"
        ) as mock_databases_names:
            mock_databases_names.return_value = (
                "information_schema",
                "mysql",
                "performance_schema",
                "sys",
                "diego",
            )
            self.assertListEqual(self.mysql.databases(), ["diego"])

            mock_databases_names.return_value = (
                "information_schema",
                "mysql",
                "performance_schema",
                "sys",
            )
            self.assertListEqual(self.mysql.databases(), [])

        with patch("mysqlserver.MySQL.is_ready") as mock_is_ready:
            mock_is_ready.return_value = False
            mock_databases_names.return_value = (
                "information_schema",
                "mysql",
                "performance_schema",
                "sys",
                "diego",
            )
            self.assertListEqual(self.mysql.databases(), [])
