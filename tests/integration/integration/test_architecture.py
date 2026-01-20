#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


from jubilant_backports import Juju

from .. import markers
from ..helpers_ha import CHARM_METADATA, MINUTE_SECS, wait_for_unit_status

APP_NAME = "mysql"
TIMEOUT = 5 * MINUTE_SECS


@markers.amd64_only
def test_arm_charm_on_amd_host(juju: Juju) -> None:
    """Tries deploying an arm64 charm on amd64 host."""
    charm = "./mysql-k8s_ubuntu@22.04-arm64.charm"

    juju.deploy(
        charm,
        APP_NAME,
        num_units=1,
        config={"profile": "testing"},
        resources={"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]},
        base="ubuntu@22.04",
    )

    juju.wait(
        ready=lambda status: all((
            *(
                wait_for_unit_status(APP_NAME, unit_name, "error")(status)
                for unit_name in status.get_units(APP_NAME)
            ),
        )),
        timeout=TIMEOUT,
    )


@markers.arm64_only
def test_amd_charm_on_arm_host(juju: Juju) -> None:
    """Tries deploying an amd64 charm on arm64 host."""
    charm = "./mysql-k8s_ubuntu@22.04-amd64.charm"

    juju.deploy(
        charm,
        APP_NAME,
        num_units=1,
        config={"profile": "testing"},
        resources={"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]},
        base="ubuntu@22.04",
    )

    juju.wait(
        ready=lambda status: all((
            *(
                wait_for_unit_status(APP_NAME, unit_name, "error")(status)
                for unit_name in status.get_units(APP_NAME)
            ),
        )),
        timeout=TIMEOUT,
    )


# TODO: add s390x test
