#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from ops.testing import Harness

from charm import MySQLOperatorCharm

CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))

logger = logging.getLogger(__name__)


@pytest.fixture
def harness():
    harness = Harness(MySQLOperatorCharm, meta=METADATA, config=CONFIG, actions=ACTIONS)
    harness.add_relation("restart", "mysql")
    patcher = patch("lightkube.core.client.GenericSyncClient")
    patcher.start()
    harness.begin()
    return harness


def _check_valid_values(_harness, field: str, accepted_values: list, is_long_field=False) -> None:
    """Check the correcteness of the passed values for a field."""
    for value in accepted_values:
        _harness.update_config({field: value})
        assert _harness.charm.config[field] == value if not is_long_field else int(value)


def _check_invalid_values(_harness, field: str, erroneus_values: list) -> None:
    """Check the incorrectness of the passed values for a field."""
    for value in erroneus_values:
        _harness.update_config({field: value})
        with pytest.raises(ValueError):
            _ = _harness.charm.config[field]


def test_profile_limit_values(harness) -> None:
    """Check that integer fields are parsed correctly."""
    erroneus_values = [599, 10**7, -354343]
    _check_invalid_values(harness, "profile-limit-memory", erroneus_values)

    valid_values = [600, 1000, 35000]
    _check_valid_values(harness, "profile-limit-memory", valid_values)


def test_profile_values(harness) -> None:
    """Test profile values."""
    erroneus_values = ["prod", "Test", "foo", "bar"]
    _check_invalid_values(harness, "profile", erroneus_values)

    accepted_values = ["production", "testing"]
    _check_valid_values(harness, "profile", accepted_values)


def test_cluster_name_values(harness) -> None:
    """Test cluster name values."""
    erroneus_values = [64 * "a", "1-cluster", "cluster$"]
    _check_invalid_values(harness, "cluster-name", erroneus_values)

    accepted_values = ["c1", "cluster_name", "cluster.name", "Cluster-name", 63 * "c"]
    _check_valid_values(harness, "cluster-name", accepted_values)
