#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


import logging

import jubilant_backports
import pytest
from jubilant_backports import Juju

from ..helpers_ha import CHARM_METADATA, MINUTE_SECS

logging.getLogger("jubilant.wait").setLevel(logging.WARNING)

MYSQL_APP_NAME = "mysql"
SCALE_APPS = 7
SCALE_UNITS = 3


@pytest.mark.abort_on_fail
def test_build_and_deploy(juju: Juju, charm):
    """Build the charm and deploy 1 units to ensure a cluster is formed."""
    config = {"profile": "testing"}

    juju.deploy(
        charm,
        MYSQL_APP_NAME,
        config=config,
        num_units=1,
        resources={"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]},
        base="ubuntu@22.04",
        trust=True,
    )

    for idx in range(SCALE_APPS):
        juju.deploy(
            "mysql-test-app",
            f"app{idx}",
            num_units=1,
            channel="latest/edge",
            config={"database_name": f"database{idx}", "sleep_interval": "2000"},
            base="ubuntu@22.04",
        )
        juju.deploy(
            "mysql-router-k8s",
            f"router{idx}",
            num_units=1,
            channel="8.0/edge",
            trust=True,
            base="ubuntu@22.04",
        )


@pytest.mark.abort_on_fail
def test_relate_all(juju: Juju):
    """Relate all the applications to the database."""
    for idx in range(SCALE_APPS):
        juju.integrate(f"{MYSQL_APP_NAME}:database", f"router{idx}:backend-database")
        juju.integrate(f"app{idx}:database", f"router{idx}:database")

    juju.wait(
        jubilant_backports.all_active,
        delay=5.0,
        timeout=25 * MINUTE_SECS,
    )


@pytest.mark.abort_on_fail
def test_scale_out(juju: Juju):
    """Scale database and routers."""
    juju.add_unit(MYSQL_APP_NAME, num_units=SCALE_UNITS - 1)
    for idx in range(SCALE_APPS):
        juju.add_unit(f"router{idx}", num_units=SCALE_UNITS - 1)

    juju.wait(
        jubilant_backports.all_active,
        delay=5.0,
        timeout=30 * MINUTE_SECS,
    )


@pytest.mark.abort_on_fail
def test_scale_in(juju: Juju):
    """Scale database and routers."""
    juju.remove_unit(MYSQL_APP_NAME, num_units=SCALE_UNITS - 1)
    for idx in range(SCALE_APPS):
        juju.remove_unit(f"router{idx}", num_units=SCALE_UNITS - 1)

    juju.wait(
        jubilant_backports.all_active,
        delay=5.0,
        timeout=15 * MINUTE_SECS,
    )
