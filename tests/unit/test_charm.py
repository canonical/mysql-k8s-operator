# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest
from unittest.mock import patch

from ops.model import ActiveStatus, WaitingStatus
from ops.testing import Harness

from charm import MysqlOperatorCharm


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(MysqlOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test_on_pebble_ready(self):
        subtests = (
            ("mysql-router", "Testing MySQL Router Pebble layer"),
            ("mysql-server", "Testing MySQL Server Pebble layer"),
        )
        for service, test_description in subtests:
            with self.subTest(msg=test_description):
                # Check the initial Pebble plan is empty
                initial_plan = self.harness.get_container_pebble_plan(service)
                self.assertEqual(initial_plan.to_dict(), {})

                # Test WaitingStatus if we can't connect to the container
                with patch("ops.model.Container.can_connect") as _can_connect:
                    _can_connect.return_value = False
                    self.harness.container_pebble_ready(service)
                    self.assertEqual(
                        self.harness.model.unit.status,
                        WaitingStatus("Waiting for pod startup to complete"),
                    )
                # Test ActiveStatus when we can connect to the container
                self.harness.container_pebble_ready(service)
                self.assertEqual(self.harness.model.unit.status, ActiveStatus())
