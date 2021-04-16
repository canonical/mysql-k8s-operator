#!/usr/bin/env python3
# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

"""
MySQLConsumer lib
"""

import json
import uuid
import logging
from ops.relation import Consumer

LIBID = "abcdef1234"  # Will change when uploding the charm to charmhub
LIBAPI = 1
LIBPATCH = 0
logger = logging.getLogger(__name__)


class MySQLConsumer(Consumer):
    """
    MySQLConsumer lib class
    """
    def __init__(self, charm, name, consumes, multi=False):
        super().__init__(charm, name, consumes, multi)
        self.charm = charm
        self.relation_name = name

    def databases(self) -> list:
        """
        List of currently available databases
        Returns:
            list: list of database names
        """
        rel_id = super()._stored.relation_id
        if rel_id:
            rel = self.framework.model.get_relation(self.relation_name, rel_id)
        else:
            rel = self.framework.model.get_relation(self.relation_name)

        relation_data = rel.data[rel.app]
        dbs = relation_data.get('databases')
        databases = json.loads(dbs) if dbs else []

        return databases

    def new_database(self):
        """
        Request creation of an additional database
        """
        if not self.charm.unit.is_leader():
            return

        rel_id = super()._stored.relation_id
        if rel_id:
            rel = self.framework.model.get_relation(self.relation_name, rel_id)
        else:
            rel = self.framework.model.get_relation(self.relation_name)

        rid = uuid.uuid4()
        db_name = "db-{}-{}".format(rel.rid, rid)
        logger.debug("CLIENT REQUEST %s", db_name)
        rel_data = rel.data[self.charm.app]
        dbs = rel_data.get('databases')
        dbs = json.loads(dbs) if dbs else []
        dbs.append(db_name)
        rel.data[self.charm.app]['databases'] = json.dumps(dbs)
