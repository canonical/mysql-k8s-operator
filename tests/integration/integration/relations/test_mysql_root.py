#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import jubilant_backports
import pytest
import yaml
from jubilant_backports import Juju

from ...helpers_ha import is_relation_joined, wait_for_apps_status

logger = logging.getLogger(__name__)

DB_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

DATABASE_APP_NAME = DB_METADATA["name"]
DATABASE_ENDPOINT = "mysql-root"
APPLICATION_APP_NAME = "mysql-test-app"
APPLICATION_ENDPOINT = "mysql"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
def test_build_and_deploy(juju: Juju, charm):
    """Build the charm and deploy 3 units to ensure a cluster is formed."""
    config = {
        "profile": "testing",
        "mysql-root-interface-user": "test-user",
        "mysql-root-interface-database": "continuous_writes",
    }
    resources = {
        "mysql-image": DB_METADATA["resources"]["mysql-image"]["upstream-source"],
    }

    (
        juju.deploy(
            charm,
            DATABASE_APP_NAME,
            config=config,
            num_units=3,
            resources=resources,
            base="ubuntu@22.04",
            trust=True,
        ),
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
    juju.integrate(
        f"{APPLICATION_APP_NAME}:{APPLICATION_ENDPOINT}",
        f"{DATABASE_APP_NAME}:{DATABASE_ENDPOINT}",
    )

    juju.wait(
        lambda status: is_relation_joined(
            status,
            APPLICATION_ENDPOINT,
            DATABASE_ENDPOINT,
            APPLICATION_APP_NAME,
            DATABASE_APP_NAME,
        )
    )

    juju.wait(
        lambda status: len(status.apps[DATABASE_APP_NAME].units) == 3,
    )
    juju.wait(
        lambda status: len(status.apps[APPLICATION_APP_NAME].units) == 2,
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
