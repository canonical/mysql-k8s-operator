#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for MySQL."""

import logging

from ops.charm import CharmBase
from ops.main import main

logger = logging.getLogger(__name__)


class MySQLOperatorCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)


if __name__ == "__main__":
    main(MySQLOperatorCharm)
