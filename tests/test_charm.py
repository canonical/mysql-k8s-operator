# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest

from ops.testing import Harness
from charm import MySQLCharm


class TestCharm(unittest.TestCase):

    def setUp(self):
        harness = Harness(MySQLCharm)
        self.addCleanup(harness.cleanup)
        harness.begin()
