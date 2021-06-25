# Copyright 2021 Canonical Ltd
# See LICENSE file for licensing details.

"""Fake classes to to test"""

from ops.charm import CharmBase
from mysqlprovider import MySQLProvider

import json

# Used to populate Fake MySQL metadata.yaml
METADATA = {"relation_name": "database", "interface_name": "mysql"}

# Template for Fake MySQL metadata.yaml
PROVIDER_META = """
name: fake-mysql-charm
provides:
  {relation_name}:
    interface: {interface_name}
"""

# Used to populate Fake MySQL config.yaml
CONFIG = {
    "relation_name": METADATA["relation_name"],
    "is_joined": True,
    "db_version": "8.0.23-3build1",  # Check key-name
    "host": "localhost",
    "port": 3306,
    "user_name": "root",
    "mysql_root_password": "D10S!",
    "available_dbs": json.dumps([]),
}

# Template for Fake MySQL charm config.yaml
CONFIG_YAML = """
options:
  relation_name:
    type: string
    description: 'Fake Relation name used for testing'
    default: {relation_name}
  is_joined:
    type: boolean
    description: 'Does charm have peers'
    default: {is_joined}
  db_version:
    type: string
    description: 'Fake MySQL version used for testing'
    default: {db_version}
  available_dbs:
    type: string
    description: 'JSON list of availabe databases'
    default: {available_dbs}
"""


class MySQL:
    """Fake mysqlserver.MySQL class"""

    def __init__(self, charm):
        self.charm = charm

    def databases(self):
        """Fake method"""
        dbs = self.charm.model.config["available_dbs"]
        return dbs

    def new_databases(self, credentials, databases):
        """Fake method"""
        return True

    def new_user(self, credentials: dict):
        """Fake method"""
        return True

    def new_dbs_and_user(self, credentials: dict, databases: list) -> bool:
        """Fake method"""
        return True


class MySQLCharm(CharmBase):
    """A Fake MySQL charm used for unit testing MySQLProvider"""

    def __init__(self, *args):
        super().__init__(*args)
        self.mysql = MySQL(self)
        self.provider = MySQLProvider(
            self,
            self.model.config["relation_name"],
            "mysql",
            self.model.config["db_version"],
        )

    @property
    def provides(self):
        """Fake method"""
        provided = {
            "provides": {"mysql": self.model.config["db_version"]},
            "config": {
                "app_name": "mysql",
                "host": "localhost",
                "port": 3306,
                "user_name": "root",
                "mysql_root_password": "D10S!",
            },
        }
        return provided

    @property
    def unit_ip(self) -> str:
        """Fake property"""
        return "10.1.51.10"
