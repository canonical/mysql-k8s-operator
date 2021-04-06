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

    @patch("mysqlserver.connect")
    def test__get_client_ok(self, mock_connect):
        mock_connect.return_value = SimpleNamespace(close=lambda: True)
        self.assertTrue(self.mysql._get_client())

    def test__get_client_fail(self):
        with self.assertRaises(Error):
            self.mysql._get_client()

    @patch("mysqlserver.MySQL._execute_query")
    def test__databases_names(self, mock__execute_query):
        returned_value = (
            ("information_schema",),
            ("mysql",),
            ("performance_schema",),
            ("sys",),
        )
        mock__execute_query.return_value = returned_value
        expected_value = (
            "information_schema",
            "mysql",
            "performance_schema",
            "sys",
        )
        self.assertEqual(self.mysql._databases_names(), expected_value)

        mock__execute_query.side_effect = Error
        self.assertEqual(self.mysql._databases_names(), ())

    @patch("mysqlserver.MySQL._execute_query")
    def test_version(self, mock__execute_query):
        returned_value = [("8.0.23-3build1",)]
        mock__execute_query.return_value = returned_value
        expected_value = "8.0.23-3build1"
        self.assertEqual(self.mysql.version(), expected_value)

        mock__execute_query.side_effect = Error
        self.assertEqual(self.mysql.version(), None)

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
