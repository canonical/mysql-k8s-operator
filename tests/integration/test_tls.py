# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from constants import CLUSTER_ADMIN_USERNAME, TLS_SSL_CERT_FILE

from .helpers import (
    app_name,
    fetch_credentials,
    get_process_pid,
    get_tls_ca,
    get_unit_address,
    is_connection_possible,
    scale_application,
    unit_file_md5,
)

logger = logging.getLogger(__name__)


METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
TLS_APP_NAME = "tls-certificates-operator"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build the charm and deploy 3 units to ensure a cluster is formed."""
    if app := await app_name(ops_test):
        if len(ops_test.model.applications[app].units) == 3:
            return
        else:
            async with ops_test.fast_forward():
                await scale_application(ops_test, app, 3)
            return

    # Build and deploy charm from local source folder
    charm = await ops_test.build_charm(".")
    resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}
    await ops_test.model.deploy(
        charm, resources=resources, application_name=APP_NAME, num_units=3, series="jammy"
    )

    # Reduce the update_status frequency until the cluster is deployed
    async with ops_test.fast_forward():
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications[APP_NAME].units) == 3
        )
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="active",
            raise_on_blocked=True,
            timeout=15 * 60,
        )


@pytest.mark.abort_on_fail
async def test_connection_before_tls(ops_test: OpsTest) -> None:
    """Ensure connections (with and without ssl) are possible before relating with TLS operator."""
    app = await app_name(ops_test)
    all_units = ops_test.model.applications[app].units

    password_result = await fetch_credentials(all_units[0], CLUSTER_ADMIN_USERNAME)
    # set global config dict once
    global config
    config = {
        "username": CLUSTER_ADMIN_USERNAME,
        "password": password_result["password"],
    }

    # Before relating to TLS charm both encrypted and unencrypted connection should be possible
    logger.info("Asserting connections before relation")
    for unit in all_units:
        unit_ip = await get_unit_address(ops_test, unit.name)
        config["host"] = unit_ip

        assert is_connection_possible(
            config, **{"ssl_disabled": False}
        ), f"❌ Encrypted connection not possible to unit {unit.name} with disabled TLS"

        assert is_connection_possible(
            config, **{"ssl_disabled": True}
        ), f"❌ Unencrypted connection not possible to unit {unit.name} with disabled TLS"


@pytest.mark.abort_on_fail
async def test_enable_tls(ops_test: OpsTest) -> None:
    """Test for encryption enablement when relation to TLS charm."""
    app = await app_name(ops_test)
    all_units = ops_test.model.applications[app].units

    # Deploy TLS Certificates operator.
    logger.info("Deploy TLS operator")
    async with ops_test.fast_forward():
        tls_config = {"generate-self-signed-certificates": "true", "ca-common-name": "Test CA"}
        await ops_test.model.deploy(TLS_APP_NAME, channel="edge", config=tls_config)
        await ops_test.model.wait_for_idle(apps=[TLS_APP_NAME], status="active", timeout=15 * 60)

    # Relate with TLS charm
    logger.info("Relate to TLS operator")
    await ops_test.model.relate(app, TLS_APP_NAME)

    # Wait for hooks start reconfiguring app
    await ops_test.model.block_until(
        lambda: ops_test.model.applications[app].status != "active", timeout=4 * 60
    )

    await ops_test.model.wait_for_idle(status="active", timeout=15 * 60)

    # After relating to only encrypted connection should be possible
    logger.info("Asserting connections after relation")
    for unit in all_units:
        unit_ip = await get_unit_address(ops_test, unit.name)
        config["host"] = unit_ip
        assert is_connection_possible(
            config, **{"ssl_disabled": False}
        ), f"❌ Encrypted connection not possible to unit {unit.name} with enabled TLS"

        assert not is_connection_possible(
            config, **{"ssl_disabled": True}
        ), f"❌ Unencrypted connection possible to unit {unit.name} with enabled TLS"

    # test for ca presence in a given unit
    logger.info("Assert TLS file exists")
    assert await get_tls_ca(ops_test, all_units[0].name), "❌ No CA found after TLS relation"


@pytest.mark.abort_on_fail
async def test_rotate_tls_key(ops_test: OpsTest) -> None:
    """Verify rotating tls private keys restarts cluster with new certificates.

    This test rotates tls private keys to randomly generated keys.
    """
    app = await app_name(ops_test)
    all_units = ops_test.model.applications[app].units
    # dict of values for cert file md5sum and mysql service PID. After resetting the
    # private keys these certificates should be updated and the mysql service should be
    # restarted
    original_tls = {}
    for unit in all_units:
        original_tls[unit.name] = {}
        original_tls[unit.name]["cert"] = await unit_file_md5(
            ops_test, unit.name, f"/var/lib/mysql/{TLS_SSL_CERT_FILE}"
        )
        original_tls[unit.name]["mysql_pid"] = await get_process_pid(
            ops_test, unit.name, "mysql", "mysqld"
        )

    # set key using auto-generated key for each unit
    for unit in ops_test.model.applications[app].units:
        action = await unit.run_action(action_name="set-tls-private-key")
        action = await action.wait()
        assert action.status == "completed", "❌ setting key failed"

    # Wait for hooks start reconfiguring app
    await ops_test.model.block_until(
        lambda: ops_test.model.applications[app].status != "active", timeout=4 * 60
    )
    await ops_test.model.wait_for_idle(apps=[app], status="active", timeout=15 * 60)

    # After updating both the external key and the internal key a new certificate request will be
    # made; then the certificates should be available and updated.
    for unit in all_units:
        new_cert_md5 = await unit_file_md5(
            ops_test, unit.name, f"/var/lib/mysql/{TLS_SSL_CERT_FILE}"
        )
        new_mysql_pid = await get_process_pid(ops_test, unit.name, "mysql", "mysqld")

        assert (
            new_cert_md5 != original_tls[unit.name]["cert"]
        ), f"cert for {unit.name} was not updated."
        assert new_mysql_pid > original_tls[unit.name]["mysql_pid"], "❌ mysqld was not restarted"

    # Asserting only encrypted connection should be possible
    logger.info("Asserting connections after relation")
    for unit in all_units:
        unit_ip = await get_unit_address(ops_test, unit.name)
        config["host"] = unit_ip
        assert is_connection_possible(
            config, **{"ssl_disabled": False}
        ), f"❌ Encrypted connection not possible to unit {unit.name} with enabled TLS"

        assert not is_connection_possible(
            config, **{"ssl_disabled": True}
        ), f"❌ Unencrypted connection possible to unit {unit.name} with enabled TLS"


@pytest.mark.abort_on_fail
async def test_disable_tls(ops_test: OpsTest) -> None:
    # Remove the relation
    app = await app_name(ops_test)
    all_units = ops_test.model.applications[app].units

    logger.info("Removing relation")
    await ops_test.model.applications[app].remove_relation(
        f"{app}:certificates", f"{TLS_APP_NAME}:certificates"
    )

    # Wait for hooks start reconfiguring app
    await ops_test.model.block_until(
        lambda: ops_test.model.applications[app].status != "active", timeout=4 * 60
    )
    await ops_test.model.wait_for_idle(apps=[app], status="active", timeout=15 * 60)

    # After relation removal both encrypted and unencrypted connection should be possible
    for unit in all_units:
        unit_ip = await get_unit_address(ops_test, unit.name)
        config["host"] = unit_ip
        assert is_connection_possible(
            config, **{"ssl_disabled": False}
        ), f"❌ Encrypted connection not possible to unit {unit.name} after relation removal"

        assert is_connection_possible(
            config, **{"ssl_disabled": True}
        ), f"❌ Unencrypted connection not possible to unit {unit.name} after relation removal"
