# Copyright 2020 Justin
# See LICENSE file for licensing details.

import unittest

from ops.testing import Harness
from charm import MySQLOperatorCharm


class TestCharm(unittest.TestCase):

    def test_config_changed(self):
        """
        TODO: Fix this test
        """
        harness = Harness(MySQLOperatorCharm)
        self.addCleanup(harness.cleanup)
        harness.begin()
        self.assertEqual(list(harness.charm._stored.things), [])
