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

    def test_new_passwod(self):
        self.assertEqual(len(self.mysql.new_password()), 16)
        self.assertEqual(len(self.mysql.new_password(50)), 50)
        self.assertEqual(len(self.mysql.new_password(0)), 0)

    def test__create_user(self):
        credentials1 = {
            "username": "DiegoArmando",
            "password": "LaPelotaNoSeMancha10!",
        }
        expected_query1 = "CREATE USER 'DiegoArmando'@'%' IDENTIFIED BY 'LaPelotaNoSeMancha10!';"
        query1 = self.mysql._create_user(credentials1)
        self.assertEqual(expected_query1, query1)

        credentials2 = {
            "username": "diego_armando",
            "password": "LaPelotaNoSeMancha20!",
        }
        expected_query2 = "CREATE USER 'DiegoArmando'@'%' IDENTIFIED BY 'LaPelotaNoSeMancha20!';"
        query2 = self.mysql._create_user(credentials2)
        self.assertNotEqual(expected_query2, query2)

    def test__create_database(self):
        database1 = "monumental"
        expected_query1 = "CREATE DATABASE monumental;"
        query1 = self.mysql._create_database(database1)
        self.assertEqual(expected_query1, query1)

        database2 = "Monumental"
        expected_query2 = "CREATE DATABASE monumental;"
        query2 = self.mysql._create_database(database2)
        self.assertNotEqual(expected_query2, query2)

    def test__grant_privileges(self):
        credentials1 = {
            "username": "DiegoArmando",
            "password": "LaPelotaNoSeMancha10!",
        }
        database1 = "Heaven"
        expected_query1 = (
            "GRANT ALL PRIVILEGES ON Heaven.* TO 'DiegoArmando'@'%';"
        )
        query1 = self.mysql._grant_privileges(credentials1, database1)
        self.assertEqual(expected_query1, query1)

        credentials2 = {
            "username": "diego_armando",
            "password": "LaPelotaNoSeMancha20!",
        }
        database2 = "Heaven"
        expected_query2 = (
            "GRANT ALL PRIVILEGES ON Heaven.* TO 'DiegoArmando'@'%';"
        )
        query2 = self.mysql._grant_privileges(credentials2, database2)
        self.assertNotEqual(expected_query2, query2)

        credentials3 = {
            "username": "DiegoArmando",
            "password": "LaPelotaNoSeMancha30!",
        }
        database3 = "Hell"
        expected_query3 = (
            "GRANT ALL PRIVILEGES ON Heaven.* TO 'DiegoArmando'@'%';"
        )
        query3 = self.mysql._grant_privileges(credentials3, database3)
        self.assertNotEqual(expected_query3, query3)

    def test__flush_privileges(self):
        expected_query1 = "FLUSH PRIVILEGES;"
        query1 = self.mysql._flush_privileges()
        self.assertEqual(expected_query1, query1)

    def test__build_queries(self):
        credentials = {
            "username": "DiegoArmando",
            "password": "LaPelotaNoSeMancha10!",
        }
        databases = ["Heaven", "Hell"]
        expected_queries = [
            "CREATE USER 'DiegoArmando'@'%' IDENTIFIED BY 'LaPelotaNoSeMancha10!';",
            "CREATE DATABASE Heaven;",
            "GRANT ALL PRIVILEGES ON Heaven.* TO 'DiegoArmando'@'%';",
            "CREATE DATABASE Hell;",
            "GRANT ALL PRIVILEGES ON Hell.* TO 'DiegoArmando'@'%';",
            "FLUSH PRIVILEGES;",
        ]
        self.assertEqual(
            "\n".join(expected_queries),
            self.mysql._build_queries(credentials, databases),
        )

    def test__build_remove_user_query(self):
        username = "DiegoArmando"
        expected_query = f"DROP USER '{username}'@'%';"
        self.assertEqual(
            expected_query, self.mysql._build_remove_user_query(username)
        )

    def test__build_drop_databases_query(self):
        databases = ["Segurola", "Habana"]
        expected_query = "DROP DATABASE Segurola;\nDROP DATABASE Habana;"
        self.assertEqual(
            expected_query, self.mysql._build_drop_databases_query(databases)
        )

    @patch("mysqlserver.MySQL._execute_query")
    def test_remove_user(self, mock__execute_query):
        returned_value = []
        mock__execute_query.return_value = returned_value
        username = "DiegoArmando"
        self.assertTrue(
            self.mysql.remove_user(username),
        )

    @patch("mysqlserver.MySQL._execute_query")
    def test_remove_user_exception(self, mock__execute_query):
        mock__execute_query.side_effect = Error
        username = "DiegoArmando"
        self.assertFalse(self.mysql.remove_user(username))

    @patch("mysqlserver.MySQL._execute_query")
    def test_drop_databases(self, mock__execute_query):
        returned_value = []
        mock__execute_query.return_value = returned_value
        databases = ["Segurola", "Habana"]
        self.assertTrue(self.mysql.drop_databases(databases))

    @patch("mysqlserver.MySQL._execute_query")
    def test_drop_databases_exception(self, mock__execute_query):
        mock__execute_query.side_effect = Error
        databases = ["Segurola", "Habana"]
        self.assertFalse(self.mysql.drop_databases(databases))

    @patch("mysqlserver.MySQL._execute_query")
    def test_new_dbs_and_user(self, mock__execute_query):
        returned_value = []
        mock__execute_query.return_value = returned_value

        credentials1 = {
            "username": "DiegoArmando",
            "password": "LaPelotaNoSeMancha10!",
        }
        database1 = ["Heaven", "Hell"]
        self.assertTrue(
            self.mysql.new_dbs_and_user(credentials1, database1),
        )

    @patch("mysqlserver.MySQL._execute_query")
    def test_new_dbs_and_user_exception(self, mock__execute_query):
        mock__execute_query.side_effect = Error
        credentials1 = {
            "username": "DiegoArmando",
            "password": "LaPelotaNoSeMancha10!",
        }
        database1 = ["Heaven", "Hell"]
        self.assertFalse(self.mysql.new_dbs_and_user(credentials1, database1))
