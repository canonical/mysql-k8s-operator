#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""MySQLProvider module"""

import json
import logging

from mysqlserver import MySQL
from ops.framework import StoredState
from ops.relation import Provider

logger = logging.getLogger(__name__)


class MySQLProvider(Provider):
    """
    MySQLProvider class
    """

    _stored = StoredState()

    def __init__(self, charm, name: str, provides: dict):
        super().__init__(charm, name, provides)
        self.charm = charm
        self._stored.set_default(consumers={})
        events = self.charm.on[name]

        self.framework.observe(
            events.relation_joined, self._on_database_relation_joined
        )
        self.framework.observe(
            events.relation_changed, self._on_database_relation_changed
        )
        self.framework.observe(
            events.relation_broken, self._on_database_relation_broken
        )

    ##############################################
    #               RELATIONS                    #
    ##############################################
    def _on_database_relation_joined(self, event):
        rel_id = event.relation.id
        creds = self.credentials(rel_id)
        creds["hostname"] = self.charm.hostname
        self.charm.mysql.new_dbs_and_user(creds, ["db_de_prueba"])  # FIXME
        data = {
            "credentials": creds,
            "databases": self.charm.mysql.databases(),
        }
        event.relation.data[self.charm.app]["data"] = json.dumps(data)

    def _on_database_relation_changed(self, event):
        """Ensure total number of databases requested are available"""
        if not self.charm.unit.is_leader():
            return

        data = event.relation.data[event.app]
        logger.debug("SERVER REQUEST DATA %s", data)
        dbs = data.get("databases")
        dbs_requested = json.loads(dbs) if dbs else []
        logger.debug("SERVER REQUEST DB %s", dbs_requested)
        dbs_available = self.charm.mysql.databases()
        logger.debug("SERVER AVAILABLE DB %s", dbs_available)
        missing = None

        if dbs_requested:
            if dbs_available:
                missing = list(set(dbs_requested) - set(dbs_available))
            else:
                missing = dbs_requested

        if missing:
            dbs_available.extend(missing)
            logger.debug("SERVER REQUEST RESPONSE %s", dbs_available)
            rel_id = event.relation.id
            creds = self.credentials(rel_id)
            self.charm.mysql.new_dbs_and_user(creds, dbs_available)
            event.relation.data[self.charm.app]["databases"] = json.dumps(
                dbs_available
            )

    def _on_database_relation_broken(self, event):
        if self.charm.model.config["autodelete"]:
            data = json.loads(event.relation.data[self.charm.app].get("data"))
            self.charm.mysql.drop_databases(data["databases"])
            self.charm.mysql.remove_user(data["credentials"]["username"])

    def is_new_relation(self, rel_id) -> bool:
        if rel_id in self._stored.consumers:
            return False
        else:
            return True

    def credentials(self, rel_id) -> dict:
        """Return MySQL credentials"""
        if self.is_new_relation(rel_id):
            creds = {
                "username": self.new_username(rel_id),
                "password": MySQL.new_password(),
            }
            self._stored.consumers[rel_id] = creds
        else:
            creds = self._stored.consumers[rel_id]
        return creds

    def new_username(self, rel_id) -> str:
        """Return username based in relation id"""
        return f"user_{rel_id}"
