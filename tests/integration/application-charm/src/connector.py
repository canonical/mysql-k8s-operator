#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import mysql.connector


class MysqlConnector:
    """Context manager for mysql connector."""

    def __init__(self, config: dict, commit: bool = True):
        """Initialize the context manager.

        Args:
            config: Configuration dict for the mysql connector, like:
                config = {
                    "user": user,
                    "password": remote_data["password"],
                    "host": host,
                    "database": database,
                    "raise_on_warnings": False,
                }
            commit: Commit the transaction after the context is exited.
        """
        self.config = config
        self.commit = commit

    def __enter__(self):
        """Create the connection and return a cursor."""
        self.connection = mysql.connector.connect(**self.config)
        self.cursor = self.connection.cursor()
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Handle transaction and connection close."""
        if self.commit:
            self.connection.commit()
        self.cursor.close()
        self.connection.close()
