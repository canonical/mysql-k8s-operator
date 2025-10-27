# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import Mock, PropertyMock, patch

import pytest
from ops.charm import ActionEvent
from ops.testing import Harness

from charm import MySQLOperatorCharm


class FakeMySQLBackend:
    """Simulates the real MySQL backend, either returning a dict or raising."""

    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error

    def get_cluster_status(self):
        """Return the preset response or raise the preset error."""
        if self._error:
            raise self._error
        return self._response


@pytest.fixture
def harness():
    """Start the charm so harness.charm exists and peer databag works."""
    harness = Harness(MySQLOperatorCharm)
    harness.begin()
    return harness


def make_event():
    """Create a dummy ActionEvent with spies on set_results() and fail()."""
    event = Mock(spec=ActionEvent)
    event.set_results = Mock()
    event.fail = Mock()
    event.params = {}  # ensure .params.get() won't AttributeError
    return event


def test_get_cluster_status_action_success(harness):
    """On success, the action wraps and forwards the status dict."""
    # Prepare peer-databag so handler finds a cluster-name
    relation = harness.add_relation("database-peers", "database-peers")
    harness.update_relation_data(relation, harness.charm.app.name, {"cluster-name": "my-cluster"})

    # Patch out the MySQL backend to return a known dict
    sample = {"clusterrole": "primary", "status": "ok"}
    fake = FakeMySQLBackend(response=sample)
    with patch.object(MySQLOperatorCharm, "_mysql", new_callable=PropertyMock, return_value=fake):
        event = make_event()

        # Invoke the action
        harness.charm._get_cluster_status(event)

        # Expect set_results called once with {'success': True, 'status': sample}
        event.set_results.assert_called_once_with({"success": True, "status": sample})
        event.fail.assert_not_called()


@pytest.mark.parametrize(
    "backend_result",
    [
        {"error": RuntimeError("boom")},
        {"response": None},  # silent failure
    ],
)
def test_get_cluster_status_action_failure(backend_result, harness):
    """On backend error, the action calls event.fail() and does not set_results()."""
    # Seed peer-databag for cluster-name lookup
    relation = harness.add_relation("database-peers", "database-peers")
    harness.update_relation_data(relation, harness.charm.app.name, {"cluster-name": "my-cluster"})

    fake = FakeMySQLBackend(**backend_result)
    with patch.object(MySQLOperatorCharm, "_mysql", new_callable=PropertyMock, return_value=fake):
        event = make_event()

        # Invoke the action
        harness.charm._get_cluster_status(event)

        # It should report failure and never set_results
        event.fail.assert_called_once()
        event.set_results.assert_not_called()
