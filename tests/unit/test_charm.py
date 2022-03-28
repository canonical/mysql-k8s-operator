# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest


class TestCharm(unittest.TestCase):
    def test_mock_pass(self):
        self.assertTrue(True)
