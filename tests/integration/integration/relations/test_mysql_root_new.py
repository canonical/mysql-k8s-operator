#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant_backports
import pytest
from jubilant_backports import Juju

from ...helpers_ha import CHARM_METADATA, MINUTE_SECS, wait_for_apps_status

logger = logging.getLogger(__name__)

DATABASE_APP_NAME = CHARM_METADATA["name"]
DATABASE_ENDPOINT = "mysql-root"
APPLICATION_APP_NAME = "mysql-test-app"
APPLICATION_ENDPOINT = "mysql"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
def test_build_and_deploy(juju: Juju, charm):
    """Build the charm and deploy 3 units to ensure a cluster is formed."""
    juju.deploy(
        charm,
        DATABASE_APP_NAME,
        config={
            "profile": "testing",
            "mysql-root-interface-user": "test-user",
            "mysql-root-interface-database": "continuous_writes",
        },
        num_units=3,
        resources={
            "mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"],
        },
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
    juju.integrate(
        f"{APPLICATION_APP_NAME}:{APPLICATION_ENDPOINT}",
        f"{DATABASE_APP_NAME}:{DATABASE_ENDPOINT}",
    )

    logger.info("Waiting for application app to be waiting...")
    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_waiting, APPLICATION_APP_NAME),
        error=jubilant_backports.any_blocked,
        timeout=15 * MINUTE_SECS,
    )
    logger.info("Waiting for database app to be active...")
    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, DATABASE_APP_NAME),
        error=jubilant_backports.any_blocked,
        timeout=15 * MINUTE_SECS,
    )
