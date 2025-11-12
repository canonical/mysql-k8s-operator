#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import jubilant_backports
import pytest
import yaml
from jubilant_backports import Juju

from ... import markers
from ...helpers_ha import (
    get_relation_data,
    wait_for_apps_status,
)

logger = logging.getLogger(__name__)

DB_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

DATABASE_APP_NAME = DB_METADATA["name"]
DATABASE_ENDPOINT = "database"
APPLICATION_APP_NAME = "mysql-test-app"
APPLICATION_ENDPOINT = "database"

APPS = [DATABASE_APP_NAME, APPLICATION_APP_NAME]


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
def test_build_and_deploy(juju: Juju, charm):
    """Build the charm and deploy 3 units to ensure a cluster is formed."""
    config = {"cluster-name": "test_cluster", "profile": "testing"}
    resources = {"mysql-image": DB_METADATA["resources"]["mysql-image"]["upstream-source"]}

    juju.deploy(
        charm,
        DATABASE_APP_NAME,
        config=config,
        num_units=3,
        resources=resources,
        base="ubuntu@22.04",
        trust=True,
    )

    juju.deploy(
        APPLICATION_APP_NAME,
        num_units=2,
        channel="latest/edge",
        base="ubuntu@22.04",
    )


@pytest.mark.abort_on_fail
def test_relation_creation_eager(juju: Juju):
    """Relate charms before they have time to properly start.

    It simulates a Terraform-like deployment strategy
    """
    logger.info("Creating relation...")
    juju.integrate(
        f"{APPLICATION_APP_NAME}:{APPLICATION_ENDPOINT}",
        f"{DATABASE_APP_NAME}:{DATABASE_ENDPOINT}",
    )

    def count_units(status: jubilant_backports.Status, app_name: str, num_units: int) -> bool:
        app = status.apps[app_name]
        return len(app.units) == num_units

    logger.info("Waiting for unit counts...")
    juju.wait(
        lambda status: count_units(status, DATABASE_APP_NAME, 3),
    )
    juju.wait(
        lambda status: count_units(status, APPLICATION_APP_NAME, 2),
    )

    logger.info("Waiting for application app to be waiting...")
    juju.wait(
        wait_for_apps_status(jubilant_backports.all_waiting, APPLICATION_APP_NAME),
        error=jubilant_backports.any_blocked,
        timeout=1000,
    )
    logger.info("Waiting for database app to be active...")
    juju.wait(
        wait_for_apps_status(jubilant_backports.all_active, DATABASE_APP_NAME),
        error=jubilant_backports.any_blocked,
        timeout=1000,
    )


@pytest.mark.abort_on_fail
@markers.only_without_juju_secrets
def test_relation_creation_databag(juju: Juju):
    """Relate charms and wait for the expected changes in status."""
    juju.wait(jubilant_backports.all_active)

    relation_data = get_relation_data(juju, APPLICATION_APP_NAME, "database")
    assert {"password", "username"} <= set(relation_data[0]["application-data"])


@pytest.mark.abort_on_fail
@markers.only_with_juju_secrets
def test_relation_creation(juju: Juju):
    """Relate charms and wait for the expected changes in status."""
    juju.wait(jubilant_backports.all_active)

    relation_data = get_relation_data(juju, APPLICATION_APP_NAME, "database")
    assert not {"password", "username"} <= set(relation_data[0]["application-data"])
    assert "secret-user" in relation_data[0]["application-data"]


@pytest.mark.abort_on_fail
def test_relation_broken(juju: Juju):
    """Remove relation and wait for the expected changes in status."""
    juju.remove_relation(
        f"{APPLICATION_APP_NAME}:{APPLICATION_ENDPOINT}",
        f"{DATABASE_APP_NAME}:{DATABASE_ENDPOINT}",
    )

    # Inspired by https://github.com/canonical/jubilant/blob/f9f785a/tests/integration/test_relations.py#L19-L24
    juju.wait(
        lambda status: not status.apps[APPLICATION_APP_NAME].relations
        and not status.apps[DATABASE_APP_NAME].relations
    )

    juju.wait(
        wait_for_apps_status(jubilant_backports.all_active, DATABASE_APP_NAME),
        error=jubilant_backports.any_blocked,
    )
    juju.wait(
        wait_for_apps_status(jubilant_backports.all_waiting, APPLICATION_APP_NAME),
        error=jubilant_backports.any_blocked,
    )
