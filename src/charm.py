#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for MySQL."""

import logging

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus

logger = logging.getLogger(__name__)


class MySQLOperatorCharm(CharmBase):
    """Operator framework charm for MySQL."""

    def __init__(self, *args):
        super().__init__(*args)

        self.framework.observe(self.on.mysql_pebble_ready, self._on_mysql_pebble_ready)

    def _on_mysql_pebble_ready(self, _):
        """Define and start a workload using the Pebble API."""
        self.unit.status = ActiveStatus()

if __name__ == "__main__":
    main(MySQLOperatorCharm)
