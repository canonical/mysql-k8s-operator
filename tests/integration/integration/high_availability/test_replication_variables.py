#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant_backports
import pytest
from jubilant_backports import Juju

from ...helpers_ha import (
    CHARM_METADATA,
    MINUTE_SECS,
    get_app_units,
    get_mysql_variable_value,
    wait_for_apps_status,
)

logger = logging.getLogger(__name__)

APP_NAME = CHARM_METADATA["name"]
CLUSTER_NAME = "test_cluster"
TIMEOUT = 15 * MINUTE_SECS


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
def test_build_and_deploy(juju: Juju, charm) -> None:
    """Build the mysql charm and deploy it."""
    logger.info(f"Deploying {APP_NAME}")
    juju.deploy(
        charm,
        APP_NAME,
        resources={"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]},
        base="ubuntu@22.04",
        config={"cluster-name": CLUSTER_NAME, "profile": "testing"},
        num_units=3,
        trust=True,
    )

    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, APP_NAME),
        timeout=TIMEOUT,
    )


@pytest.mark.abort_on_fail
def test_custom_variables(juju: Juju) -> None:
    """Query database for custom variables."""
    app_units = get_app_units(juju, APP_NAME)

    custom_vars = {}
    custom_vars["max_connections"] = 100
    custom_vars["innodb_buffer_pool_size"] = 20971520
    custom_vars["innodb_buffer_pool_chunk_size"] = 1048576
    custom_vars["group_replication_message_cache_size"] = 134217728

    for unit_name in app_units:
        for k, v in custom_vars.items():
            logger.info(f"Checking that {k} is set to {v} on {unit_name}")
            value = get_mysql_variable_value(juju, APP_NAME, unit_name, k)
            assert int(value) == v, f"Variable {k} is not set to {v}"
