# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import random
import subprocess
import tempfile
from pathlib import Path
from string import Template

import jubilant_backports
import pytest
from jubilant_backports import Juju

from ...helpers_ha import (
    CHARM_METADATA,
    check_mysql_instances_online,
    check_mysql_units_writes_increment,
    get_app_units,
    get_mysql_primary_unit,
    update_interval,
    wait_for_apps_status,
    wait_for_unit_status,
)

MYSQL_APP_NAME = "mysql-k8s"
MYSQL_TEST_APP_NAME = "mysql-test-app"

MINUTE_SECS = 60


@pytest.mark.abort_on_fail
def test_deploy_highly_available_cluster(juju: Juju, charm: str) -> None:
    """Simple test to ensure that the MySQL and application charms get deployed."""
    logging.info("Deploying MySQL cluster")
    juju.deploy(
        charm=charm,
        app=MYSQL_APP_NAME,
        base="ubuntu@22.04",
        config={"profile": "testing"},
        resources={"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]},
        num_units=3,
    )
    juju.deploy(
        charm=MYSQL_TEST_APP_NAME,
        app=MYSQL_TEST_APP_NAME,
        base="ubuntu@22.04",
        channel="latest/edge",
        config={"sleep_interval": 300},
        num_units=1,
    )

    juju.integrate(
        f"{MYSQL_APP_NAME}:database",
        f"{MYSQL_TEST_APP_NAME}:database",
    )

    logging.info("Wait for applications to become active")
    juju.wait(
        ready=wait_for_apps_status(
            jubilant_backports.all_active, MYSQL_APP_NAME, MYSQL_TEST_APP_NAME
        ),
        error=jubilant_backports.any_blocked,
        timeout=20 * MINUTE_SECS,
    )


@pytest.mark.abort_on_fail
def test_network_cut_affecting_an_instance(juju: Juju, continuous_writes, chaos_mesh) -> None:
    """Test for a network cut affecting an instance."""
    logging.info("Ensuring that all instances have incrementing continuous writes")
    check_mysql_units_writes_increment(juju, MYSQL_APP_NAME)

    mysql_units = get_app_units(juju, MYSQL_APP_NAME)
    mysql_primary = get_mysql_primary_unit(juju, MYSQL_APP_NAME)

    logging.info("Creating network-chaos policy")
    create_instance_isolation_config(juju, mysql_primary)

    online_units = set(mysql_units) - {mysql_primary}
    online_units = list(online_units)
    random_unit = random.choice(online_units)

    logging.info("Checking whether the remaining units are online")
    assert check_mysql_instances_online(juju, MYSQL_APP_NAME, online_units)
    check_mysql_units_writes_increment(juju, MYSQL_APP_NAME, online_units)

    new_mysql_primary = get_mysql_primary_unit(juju, MYSQL_APP_NAME, random_unit)
    assert new_mysql_primary != mysql_primary

    logging.info("Removing network-chaos policy")
    remove_instance_isolation_config(juju)

    with update_interval(juju, "10s"):
        logging.info("Wait until returning instance enters recovery")
        juju.wait(
            ready=wait_for_unit_status(MYSQL_APP_NAME, mysql_primary, "active"),
            timeout=20 * MINUTE_SECS,
        )

    logging.info("Check that all units are online")
    assert check_mysql_instances_online(juju, MYSQL_APP_NAME, online_units)

    logging.info("Ensuring that all instances have incrementing continuous writes")
    check_mysql_units_writes_increment(juju, MYSQL_APP_NAME)


def create_instance_isolation_config(juju: Juju, unit_name: str) -> None:
    """Create a NetworkChaos config to use chaos-mesh to simulate a network cut."""
    network_loss_config_path = (
        "tests/integration/integration/high_availability/manifests/chaos_network_loss.yml"
    )

    with tempfile.NamedTemporaryFile(dir=Path.home()) as temp_file:
        with open(network_loss_config_path) as network_loss_file:
            contents = network_loss_file.read()
            template = Template(contents).substitute(
                namespace=juju.model,
                pod=unit_name.replace("/", "-"),
            )

            temp_file.write(str.encode(template))
            temp_file.flush()

        env = os.environ
        env["KUBECONFIG"] = os.path.expanduser("~/.kube/config")

        try:
            subprocess.check_output(["microk8s.kubectl", "apply", "-f", temp_file.name], env=env)
        except subprocess.CalledProcessError as e:
            logging.error(e.output)
            logging.error(e.stderr)
            raise


def remove_instance_isolation_config(juju: Juju) -> None:
    """Delete the NetworkChaos that is isolating the primary unit of the cluster."""
    env = os.environ
    env["KUBECONFIG"] = os.path.expanduser("~/.kube/config")

    subprocess.check_output(
        [
            "microk8s.kubectl",
            f"--namespace={juju.model}",
            "delete",
            "networkchaos",
            "network-loss-primary",
        ],
        env=env,
    )
