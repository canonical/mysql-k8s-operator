# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
from time import sleep

import jubilant_backports
import pytest
from jubilant_backports import Juju

from constants import CLUSTER_ADMIN_USERNAME, CONTAINER_NAME, TLS_SSL_CERT_FILE

from .. import architecture, juju_
from ..helpers import (
    is_connection_possible,
)
from ..helpers_ha import (
    CHARM_METADATA,
    MINUTE_SECS,
    get_app_units,
    get_mysql_server_credentials,
    get_unit_address,
    get_unit_info,
    wait_for_apps_status,
)

logger = logging.getLogger(__name__)

logging.getLogger("jubilant.wait").setLevel(logging.WARNING)

APP_NAME = CHARM_METADATA["name"]
CLUSTER_NAME = "test_cluster"
MODEL_CONFIG = {"logging-config": "<root>=INFO;unit=DEBUG"}
TLS_SETUP_SLEEP_TIME = 30
TIMEOUT = 15 * MINUTE_SECS

if juju_.has_secrets:
    tls_app_name = "self-signed-certificates"
    tls_channel = "1/stable"
    tls_config = {"ca-common-name": "Test CA"}
    tls_base = "ubuntu@24.04"
else:
    tls_app_name = "tls-certificates-operator"
    tls_channel = "legacy/edge" if architecture.architecture == "arm64" else "legacy/stable"
    tls_config = {"generate-self-signed-certificates": "true", "ca-common-name": "Test CA"}
    tls_base = "ubuntu@22.04"

# Global config dictionary for connection testing
config = {}


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
def test_build_and_deploy(juju: Juju, charm) -> None:
    """Build the charm and deploy 3 units to ensure a cluster is formed."""
    # Set model configuration
    juju.model_config(MODEL_CONFIG)

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
def test_connection_before_tls(juju: Juju) -> None:
    """Ensure connections (with and without ssl) are possible before relating with TLS operator."""
    app_units = get_app_units(juju, APP_NAME)

    password_result = get_mysql_server_credentials(juju, app_units[0], CLUSTER_ADMIN_USERNAME)
    # set global config dict once
    global config
    config = {
        "username": CLUSTER_ADMIN_USERNAME,
        "password": password_result["password"],
    }

    # Before relating to TLS charm both encrypted and unencrypted connection should be possible
    logger.info("Asserting connections before relation")
    for unit_name in app_units:
        unit_ip = get_unit_address(juju, APP_NAME, unit_name)
        config["host"] = unit_ip

        assert is_connection_possible(config, **{"ssl_disabled": False}), (
            f"❌ Encrypted connection not possible to unit {unit_name} with disabled TLS"
        )

        assert is_connection_possible(config, **{"ssl_disabled": True}), (
            f"❌ Unencrypted connection not possible to unit {unit_name} with disabled TLS"
        )


@pytest.mark.abort_on_fail
def test_enable_tls(juju: Juju) -> None:
    """Test for encryption enablement when relation to TLS charm."""
    app_units = get_app_units(juju, APP_NAME)

    # Deploy TLS Certificates operator.
    logger.info("Deploy TLS operator")
    juju.deploy(
        tls_app_name,
        channel=tls_channel,
        config=tls_config,
        base=tls_base,
    )
    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, tls_app_name),
        timeout=TIMEOUT,
    )

    # Relate with TLS charm
    logger.info("Relate to TLS operator")
    juju.integrate(APP_NAME, tls_app_name)

    # allow time for TLS enablement
    sleep(TLS_SETUP_SLEEP_TIME)

    # After relating to only encrypted connection should be possible
    logger.info("Asserting connections after relation")
    for unit_name in app_units:
        unit_ip = get_unit_address(juju, APP_NAME, unit_name)
        config["host"] = unit_ip
        assert is_connection_possible(config, **{"ssl_disabled": False}), (
            f"❌ Encrypted connection not possible to unit {unit_name} with enabled TLS"
        )

        assert not is_connection_possible(config, **{"ssl_disabled": True}), (
            f"❌ Unencrypted connection possible to unit {unit_name} with enabled TLS"
        )

    # test for ca presence in a given unit
    logger.info("Assert TLS file exists")
    assert get_tls_ca(juju, app_units[0]), "❌ No CA found after TLS relation"


@pytest.mark.abort_on_fail
def test_rotate_tls_key(juju: Juju) -> None:
    """Verify rotating tls private keys restarts cluster with new certificates.

    This test rotates tls private keys to randomly generated keys.
    """
    app_units = get_app_units(juju, APP_NAME)
    # dict of values for cert file md5sum. After resetting the
    # private keys these certificates should be updated.
    original_tls = {}
    for unit_name in app_units:
        original_tls[unit_name] = {}
        original_tls[unit_name]["cert"] = unit_file_md5(
            juju, unit_name, f"/var/lib/mysql/{TLS_SSL_CERT_FILE}"
        )

    # set key using auto-generated key for each unit
    for unit_name in app_units:
        task = juju.run(
            unit=unit_name,
            action="set-tls-private-key",
        )
        task.raise_on_failure()

    # allow time for reconfiguration
    sleep(TLS_SETUP_SLEEP_TIME)

    # After updating both the external key and the internal key a new certificate request will be
    # made; then the certificates should be available and updated.
    for unit_name in app_units:
        new_cert_md5 = unit_file_md5(juju, unit_name, f"/var/lib/mysql/{TLS_SSL_CERT_FILE}")

        assert new_cert_md5 != original_tls[unit_name]["cert"], (
            f"cert for {unit_name} was not updated."
        )

    # Asserting only encrypted connection should be possible
    logger.info("Asserting connections after relation")
    for unit_name in app_units:
        unit_ip = get_unit_address(juju, APP_NAME, unit_name)
        config["host"] = unit_ip
        assert is_connection_possible(config, **{"ssl_disabled": False}), (
            f"❌ Encrypted connection not possible to unit {unit_name} with enabled TLS"
        )

        assert not is_connection_possible(config, **{"ssl_disabled": True}), (
            f"❌ Unencrypted connection possible to unit {unit_name} with enabled TLS"
        )


@pytest.mark.abort_on_fail
def test_disable_tls(juju: Juju) -> None:
    # Remove the relation
    app_units = get_app_units(juju, APP_NAME)

    logger.info("Removing relation")
    juju.remove_relation(f"{APP_NAME}:certificates", f"{tls_app_name}:certificates")

    # Allow time for reconfigure
    sleep(TLS_SETUP_SLEEP_TIME)

    # After relation removal both encrypted and unencrypted connection should be possible
    for unit_name in app_units:
        unit_ip = get_unit_address(juju, APP_NAME, unit_name)
        config["host"] = unit_ip
        assert is_connection_possible(config, **{"ssl_disabled": False}), (
            f"❌ Encrypted connection not possible to unit {unit_name} after relation removal"
        )

        assert is_connection_possible(config, **{"ssl_disabled": True}), (
            f"❌ Unencrypted connection not possible to unit {unit_name} after relation removal"
        )


def get_tls_ca(juju: Juju, unit_name: str) -> str:
    """Returns the TLS CA used by the unit.

    Args:
        juju: The Juju instance
        unit_name: The name of the unit

    Returns:
        TLS CA or an empty string if there is no CA.
    """
    unit_info = get_unit_info(juju, unit_name)
    if not unit_info:
        raise ValueError(f"no unit info could be grabbed for {unit_name}")

    # Filter the data based on the relation name.
    relation_data = [
        v for v in unit_info[unit_name]["relation-info"] if v["endpoint"] == "certificates"
    ]
    if len(relation_data) == 0:
        return ""
    return json.loads(relation_data[0]["application-data"]["certificates"])[0].get("ca")


def unit_file_md5(juju: Juju, unit_name: str, file_path: str) -> str | None:
    """Return md5 hash for given file.

    Args:
        juju: The Juju instance
        unit_name: The name of the unit
        file_path: The path to the file

    Returns:
        md5sum hash string
    """
    try:
        md5sum_raw = juju.ssh(
            command=f"md5sum {file_path}",
            target=unit_name,
            container=CONTAINER_NAME,
        )
        return md5sum_raw.strip().split()[0]
    except Exception:
        return
