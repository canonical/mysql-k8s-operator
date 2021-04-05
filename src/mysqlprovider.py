#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
from ops.relation import Provider

logger = logging.getLogger(__name__)


class MySQLProvider(Provider):
    """
    MySQLProvider class
    """

    def __init__(self, charm, name, provides):
        super().__init__(charm, name, provides)
        self.charm = charm
        events = self.charm.on[name]
        self.framework.observe(
            events.relation_changed, self.on_database_relation_changed
        )

    ##############################################
    #               RELATIONS                    #
    ##############################################
    def on_database_relation_changed(self, event):
        """Ensure total number of databases requested are available"""
        if not self.charm.unit.is_leader():
            return

        data = event.relation.data[event.app]
        logger.debug("SERVER REQUEST DATA %s", data)
        dbs = data.get("databases")
        dbs_requested = json.loads(dbs) if dbs else []
        logger.debug("SERVER REQUEST DB %s", dbs_requested)
        dbs_available = self.charm.mongo.databases
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
            event.relation.data[self.charm.app]["databases"] = json.dumps(
                dbs_available
            )
