"""
## Overview

This document explains how to integrate with the MySQL charm for the purposes of consuming a mysql database. It also explains how alternative implementations of the MySQL charm may maintain the same interface and be backward compatible with all currently integrated charms. Finally this document is the authoritative reference on the structure of relation data that is shared between MySQL charms and any other charm that intends to use the database.


## Consumer Library Usage

The MySQL charm library uses the [Provider and Consumer](https://ops.readthedocs.io/en/latest/#module-ops.relation) objects from the Operator Framework. Charms that would like to use a MySQL database must use the `MySQLConsumer` object from the charm library. Using the `MySQLConsumer` object requires instantiating it, typically in the constructor of your charm. The `MySQLConsumer` constructor requires the name of the relation over which a database will be used. This relation must use the `mysql_datastore` interface. In addition the constructor also requires a `consumes` specification, which is a dictionary with key `mysql` (also see Provider Library Usage below) and a value that represents the minimum acceptable version of MySQL. This version string can be in any format that is compatible with the Python [Semantic Version module](https://pypi.org/project/semantic-version/). For example, assuming your charm consumes a database over a rlation named "monitoring", you may instantiate `MySQLConsumer` as follows:

    from charms.mysql_k8s.v0.mysql import MySQLConsumer
    def __init__(self, *args):
        super().__init__(*args)
        ...
        self.mysql_consumer = MySQLConsumer(
            self, "monitoring", {"mysql": ">=8"}
        )
        ...

This example hard codes the consumes dictionary argument containing the minimal MySQL version required, however you may want to consider generating this dictionary by some other means, such as a `self.consumes` property in your charm. This is because the minimum required MySQL version may change when you upgrade your charm. Of course it is expected that you will keep this version string updated as you develop newer releases of your charm. If the version string can be determined at run time by inspecting the actual deployed version of your charmed application, this would be ideal.
An instantiated `MySQLConsumer` object may be used to request new databases using the `new_database()` method. This method requires no arguments unless you require multiple databases. If multiple databases are requested, you must provide a unique `name_suffix` argument. For example:

    def _on_database_relation_joined(self, event):
        self.mysql_consumer.new_database(name_suffix="db1")
        self.mysql_consumer.new_database(name_suffix="db2")

The `address`, `port`, `databases`, and `credentials` methods can all be called
to get the relevant information from the relation data.
"""

#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import uuid
import logging
from ops.relation import ConsumerBase

LIBID = "abcdef1234"  # Will change when uploding the charm to charmhub
LIBAPI = 1
LIBPATCH = 0
logger = logging.getLogger(__name__)


class MySQLConsumer(ConsumerBase):
    """
    MySQLConsumer lib class
    """

    def __init__(self, charm, name, consumes, multi=False):
        super().__init__(charm, name, consumes, multi)
        self.charm = charm
        self.relation_name = name

    def databases(self, rel_id=None) -> list:
        """
        List of currently available databases
        Returns:
            list: list of database names
        """

        rel = self.framework.model.get_relation(self.relation_name, rel_id)
        relation_data = rel.data[rel.app]
        dbs = relation_data.get("databases")
        databases = json.loads(dbs) if dbs else []

        return databases

    def new_database(self, rel_id=None, name_suffix=""):
        """
        Request creation of an additional database
        """
        if not self.charm.unit.is_leader():
            return

        rel = self.framework.model.get_relation(self.relation_name, rel_id)

        if name_suffix:
            name_suffix = "_{}".format(name_suffix)

        rid = str(uuid.uuid4()).split("-")[-1]
        db_name = "db_{}_{}_{}".format(rel.id, rid, name_suffix)
        logger.debug("CLIENT REQUEST %s", db_name)
        rel_data = rel.data[self.charm.app]
        dbs = rel_data.get("databases")
        dbs = json.loads(dbs) if dbs else []
        dbs.append(db_name)
        rel.data[self.charm.app]["databases"] = json.dumps(dbs)
