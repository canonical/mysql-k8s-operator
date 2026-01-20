#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import jubilant_backports
import pytest
from jubilant_backports import CLIError, Juju
from tenacity import RetryError, Retrying, retry_if_exception_type, stop_after_attempt, wait_fixed

from ..helpers_ha import CHARM_METADATA, MINUTE_SECS, wait_for_apps_status, wait_for_unit_status

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

    # Wait until deployment is complete in attempt to reduce CPU stress
    retry_if_cli_error(
        lambda: juju.wait(
            wait_for_apps_status(
                jubilant_backports.all_active,
                MYSQL_APP_NAME,
            ),
            delay=5.0,
            timeout=25 * MINUTE_SECS,
        )
    )
    retry_if_cli_error(
        lambda: juju.wait(
            wait_for_apps_status(
                jubilant_backports.all_waiting,
                *(f"app{idx}" for idx in range(SCALE_APPS)),
            ),
            delay=5.0,
            timeout=25 * MINUTE_SECS,
        )
    )
    retry_if_cli_error(
        lambda: juju.wait(
            ready=lambda status: all((
                *(
                    wait_for_unit_status(f"router{idx}", unit_name, "waiting")(status)
                    for idx in range(SCALE_APPS)
                    for unit_name in status.get_units(f"router{idx}")
                ),
            )),
            delay=5.0,
            timeout=25 * MINUTE_SECS,
        )
    )


@pytest.mark.abort_on_fail
def test_relate_all(juju: Juju):
    """Relate all the applications to the database."""
    for idx in range(SCALE_APPS):
        retry_if_cli_error(
            lambda idx=idx: juju.integrate(
                f"{MYSQL_APP_NAME}:database", f"router{idx}:backend-database"
            )
        )
        retry_if_cli_error(
            lambda idx=idx: juju.integrate(f"app{idx}:database", f"router{idx}:database")
        )

    retry_if_cli_error(
        lambda: juju.wait(
            jubilant_backports.all_active,
            delay=5.0,
            timeout=25 * MINUTE_SECS,
        )
    )


@pytest.mark.abort_on_fail
def test_scale_out(juju: Juju):
    """Scale database and routers."""
    retry_if_cli_error(lambda: juju.add_unit(MYSQL_APP_NAME, num_units=SCALE_UNITS - 1))
    for idx in range(SCALE_APPS):
        retry_if_cli_error(
            lambda idx=idx: juju.add_unit(f"router{idx}", num_units=SCALE_UNITS - 1)
        )

    retry_if_cli_error(
        lambda: juju.wait(
            jubilant_backports.all_active,
            delay=5.0,
            timeout=30 * MINUTE_SECS,
        )
    )


@pytest.mark.abort_on_fail
def test_scale_in(juju: Juju):
    """Scale database and routers."""
    retry_if_cli_error(lambda: juju.remove_unit(MYSQL_APP_NAME, num_units=SCALE_UNITS - 1))
    for idx in range(SCALE_APPS):
        retry_if_cli_error(
            lambda idx=idx: juju.remove_unit(f"router{idx}", num_units=SCALE_UNITS - 1)
        )

    retry_if_cli_error(
        lambda: juju.wait(
            jubilant_backports.all_active,
            delay=5.0,
            timeout=15 * MINUTE_SECS,
        )
    )


# All jubilant.Juju operations risk raising intermittent CLIErrors under CPU pressure,
# so we wrap each of them
def retry_if_cli_error(fn, *, max_attempts=10):
    try:
        for attempt in Retrying(
            retry=retry_if_exception_type(CLIError),
            stop=stop_after_attempt(max_attempts),
            wait=wait_fixed(10),
        ):
            with attempt:
                fn()

    except RetryError as exc:
        raise AssertionError(
            f"Operation failed after {max_attempts} attempts"
        ) from exc.last_attempt.exception()
