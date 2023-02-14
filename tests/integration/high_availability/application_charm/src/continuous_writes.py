# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""This file is meant to run in the background continuously writing entries to MySQL."""

import sys
from typing import Dict

import mysql.connector

from connector import MySQLConnector  # isort: skip


def continuous_writes(database_config: Dict, table_name: str, starting_number: int) -> None:
    """Continuously write to the MySQL cluster.

    Args:
        database_config: a dictionary with MySQL config to connect to the database
        database_name: the database name where the table continuously written to exists
        table_name: the table name to direct continuous writes to
        starting_number: number from which to start writing data to the table (and increment from)
    """
    try:
        with MySQLConnector(database_config) as cursor:
            cursor.execute(
                f"CREATE TABLE IF NOT EXISTS `{table_name}`(number INTEGER, PRIMARY KEY(number));"
            )
    except Exception:
        pass

    next_value_to_insert = starting_number

    while True:
        try:
            with MySQLConnector(database_config) as cursor:
                cursor.execute(
                    f"INSERT INTO `{table_name}`(number) VALUES ({next_value_to_insert})"
                )
        except mysql.connector.errors.DatabaseError as e:
            if e.errno == 1062:
                with MySQLConnector(database_config) as cursor:
                    cursor.execute(f"SELECT max(number) FROM `{table_name}`")
                    result = cursor.fetchall()
                    next_value_to_insert = result[0][0] + 1
                continue
            continue
        except Exception:
            continue

        next_value_to_insert += 1


def main():
    [_, username, password, host, port, database, table_name, starting_number] = sys.argv
    database_config = {
        "user": username,
        "password": password,
        "host": host,
        "port": port,
        "database": database,
    }

    continuous_writes(database_config, table_name, int(starting_number))


if __name__ == "__main__":
    main()
