#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


import logging

import jubilant_backports
import pytest
from jubilant_backports import Juju

from ..helpers_ha import CHARM_METADATA, MINUTE_SECS, scale_app_units

logging.getLogger("jubilant.wait").setLevel(logging.WARNING)

SCALE_APPS = 7
SCALE_UNITS = 3


@pytest.mark.abort_on_fail
def test_build_and_deploy(juju: Juju, charm):
    """Build the charm and deploy 1 units to ensure a cluster is formed."""
    config = {"profile": "testing"}

    juju.deploy(
        charm,
        "mysql",
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
        juju.integrate("mysql:database", f"router{idx}:backend-database")
        juju.integrate(f"app{idx}:database", f"router{idx}:database")

    juju.wait(
        jubilant_backports.all_active,
        timeout=25 * MINUTE_SECS,
    )


@pytest.mark.abort_on_fail
def test_scale_out(juju: Juju):
    """Scale database and routers."""
    scale_app_units(juju, "mysql", SCALE_UNITS)
    for idx in range(SCALE_APPS):
        scale_app_units(juju, f"router{idx}", SCALE_UNITS)

    juju.wait(
        jubilant_backports.all_active,
        timeout=30 * MINUTE_SECS,
    )


@pytest.mark.abort_on_fail
def test_scale_in(juju: Juju):
    """Scale database and routers."""
    scale_app_units(juju, "mysql", 1)
    for idx in range(SCALE_APPS):
        scale_app_units(juju, f"router{idx}", 1)

    juju.wait(
        jubilant_backports.all_active,
        timeout=15 * MINUTE_SECS,
    )
