#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from mysql.connector import connect, Error

logger = logging.getLogger(__name__)


class MySQL:
    """MySQL class docstring"""

    def __init__(self, config):
        self.app_name = config["app_name"]
        self.host = config["host"]
        self.port = config["port"]
        self.user_name = config["user_name"]
        self.mysql_root_password = config["mysql_root_password"]

    def _get_client(self):
        """Returns MySQL connection"""
        connection = None
        try:
            connection = connect(
                host=self.host,
                user=self.user_name,
                passwd=self.mysql_root_password,
            )
            return connection
        except Error as e:
            raise e

    def is_ready(self) -> bool:
        """Returns if MySQL is up and running"""
        ready = False

        try:
            client = self._get_client()
            ready = True
            if client is not None:
                logger.warning("MySQL service is ready.")
                client.close()
        except Error as e:
            logger.warning("MySQL is not ready yet. - %s", e)

        return ready

    def _execute_query(self, query) -> tuple:
        """Execute SQL query"""
        client = self._get_client()
        cursor = client.cursor()
        cursor.execute(query)
        return cursor.fetchall()

    def _databases_names(self) -> tuple:
        """Get databases names"""
        databases = ()
        try:
            query = "SHOW DATABASES;"
            databases = tuple(x[0] for x in self._execute_query(query))
            return databases
        except Error as e:
            logger.warning(e)
            return databases

    def databases(self) -> list:
        """List all databases currently available"""
        if not self.is_ready():
            return []

        # gather list of no default databases
        defaultdbs = (
            "information_schema",
            "mysql",
            "performance_schema",
            "sys",
        )
        dbs = self._databases_names()
        databases = [db for db in dbs if db not in defaultdbs]
        return databases

    def version(self) -> str:
        """Get MySQLDB version"""
        try:
            query = "SELECT VERSION() as version;"
            version = self._execute_query(query)[0][0]
            return version
        except Error:
            logger.warning("VERSION NOT READY YET")
            return None
