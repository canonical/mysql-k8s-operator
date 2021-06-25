#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import secrets
import string

from mysql.connector import connect, Error
from typing import Union

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
            if client is not None:
                logger.debug("MySQL service is ready.")
                client.close()
                ready = True
        except Error as e:
            logger.debug("MySQL is not ready yet. - %s", e)

        return ready

    def _execute_query(self, query) -> tuple:
        """Execute SQL query"""
        client = self._get_client()
        cursor = client.cursor()
        cursor.execute(query)
        return cursor.fetchall()

    def _databases_names(self) -> tuple:
        """Get databases names"""
        try:
            query = "SHOW DATABASES;"
            databases = tuple(x[0] for x in self._execute_query(query))
            return databases
        except Error as e:
            logger.warning(e)
            return ()

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

    def new_user(self, credentials: dict):
        try:
            query = self._create_user(credentials)
            self._execute_query(query)
            return True
        except Error as e:
            logger.error(e)
            return False
            # Should we set BlockedStatus ?

    def new_super_user(self, credentials: dict):
        if self._user_exists(credentials["username"]):
            raise Exception(f"User already exists: {credentials['username']}")

        create_user = self._create_user(credentials)
        self._execute_query(create_user)
        grant = self._grant_privileges(credentials, "*")
        self._execute_query(grant)
        return True

    def drop_user(self, username: str) -> bool:
        if not self._user_exists(username):
            raise Exception(f"User does not exists: {username}")

        query = self._build_drop_user_query(username)
        self._execute_query(query)
        return True

    def set_user_password(self, credentials: dict):
        if not self._user_exists(credentials["username"]):
            raise Exception(f"User does not exists: {credentials['username']}")

        create_user = self._change_user_password(credentials)
        self._execute_query(create_user)
        return True

    def new_database(self, database: str):
        if self._database_exists(database):
            raise Exception(f"Database already exists: {database}")

        create_database = self._create_database(database)
        self._execute_query(create_database)
        return True

    def _user_exists(self, username):
        query = f"SELECT count(1) FROM mysql.user WHERE user = '{username}';"
        result = self._execute_query(query)

        if int(result[0][0]) == 1:
            return True
        return False

    def _database_exists(self, database):
        query = f"SELECT count(1) FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = '{database}';"
        result = self._execute_query(query)

        if int(result[0][0]) == 1:
            return True
        return False

    def _build_drop_user_query(self, username: str) -> str:
        query = f"DROP USER IF EXISTS `{username}`;"
        logger.debug("Generating query to drop user: %s", username)
        return query

    def drop_databases(self, databases: list) -> bool:
        try:
            queries = self._build_drop_databases_query(databases)
            self._execute_query(queries)
            return True
        except Error as e:
            logger.error(e)
            return False
            # Should we set BlockedStatus ?

    def _build_drop_databases_query(self, databases: list) -> str:
        queries = []
        for database in databases:
            queries.append(f"DROP DATABASE IF EXISTS `{database}`;")
            logger.debug("Generating query to drop database: %s", database)

        return "\n".join(queries)

    def new_dbs_and_user(self, credentials: dict, databases: list) -> bool:
        try:
            queries = self._build_queries(credentials, databases)
            self._execute_query(queries)
            return True
        except Error as e:
            logger.error(e)
            return False
            # Should we set BlockedStatus ?

    def _build_queries(self, credentials: dict, databases: list) -> str:
        queries = []
        queries.append(self._create_user(credentials))

        for database in databases:
            queries.append(self._create_database(database))
            queries.append(self._grant_privileges(credentials, database))

        queries.append(self._flush_privileges())
        return "\n".join(queries)

    def _create_user(self, credentials: dict) -> str:
        """Creates the query string for creating user in MySQL"""
        return "CREATE USER IF NOT EXISTS '{}'@'%' IDENTIFIED BY '{}';".format(
            credentials["username"], credentials["password"]
        )

    def _change_user_password(self, credentials: dict) -> str:
        """Creates the query string for creating user in MySQL"""
        return "ALTER USER '{}'@'%' IDENTIFIED BY '{}';".format(
            credentials["username"], credentials["password"]
        )

    def _create_database(self, database: str) -> str:
        """Creates the query string for creating database in MySQL"""
        return f"CREATE DATABASE {database};"

    def _grant_privileges(self, credentials: dict, database: str) -> str:
        """Creates the query string for granting privileges in MySQL"""
        return "GRANT ALL PRIVILEGES ON {}.* TO '{}'@'%';".format(
            database, credentials["username"]
        )

    def _flush_privileges(self) -> str:
        """Creates the query string for flushing privileges in MySQL"""
        return "FLUSH PRIVILEGES;"

    def version(self) -> Union[str, None]:
        """Get MySQLDB version"""
        try:
            query = "SELECT VERSION() as version;"
            version = self._execute_query(query)[0][0].split("-")[0]
            return version
        except Error:
            logger.debug("VERSION NOT READY YET")
            return None

    @staticmethod
    def new_password(length: int = 16) -> str:
        """Generates a password"""
        # This is a generic function.
        # It should be placed in ops. See issue: 536
        choices = string.ascii_letters + string.digits
        return "".join([secrets.choice(choices) for i in range(length)])
