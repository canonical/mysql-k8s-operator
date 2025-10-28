# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant_backports
import pytest
from jubilant_backports import Juju
from lightkube.core.client import Client
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import PersistentVolume, PersistentVolumeClaim, Pod

from .high_availability_helpers_new import (
    CHARM_METADATA,
    check_mysql_units_writes_increment,
    get_k8s_pod,
    get_k8s_pod_pvcs,
    get_k8s_pod_pvs,
    get_mysql_primary_unit,
    update_interval,
    wait_for_apps_status,
)

MYSQL_APP_NAME = "mysql-k8s"
MYSQL_TEST_APP_NAME = "mysql-test-app"

MINUTE_SECS = 60

logging.getLogger("jubilant.wait").setLevel(logging.WARNING)


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
def test_pod_eviction_and_pvc_deletion(juju: Juju, continuous_writes_new) -> None:
    """Test behavior when node drains - pod is evicted and pvs are rotated."""
    logging.info("Ensuring that all instances have incrementing continuous writes")
    check_mysql_units_writes_increment(juju, MYSQL_APP_NAME)

    mysql_primary = get_mysql_primary_unit(juju, MYSQL_APP_NAME)
    primary_pod = get_k8s_pod(juju, mysql_primary)
    primary_pod_pvcs = get_k8s_pod_pvcs(juju, mysql_primary)
    primary_pod_pvs = get_k8s_pod_pvs(juju, mysql_primary)

    logging.info(f"Evicting primary node {mysql_primary} and deleting its PVCs")
    evict_pod(primary_pod)
    delete_pvcs(primary_pod_pvcs)
    delete_pvs(primary_pod_pvs)

    with update_interval(juju, "90s"):
        logging.info("Waiting for evicted primary pod to be rescheduled")
        juju.wait(
            ready=wait_for_apps_status(jubilant_backports.all_active, MYSQL_APP_NAME),
            error=jubilant_backports.any_blocked,
            timeout=20 * MINUTE_SECS,
        )

    logging.info("Ensuring that all instances have incrementing continuous writes")
    check_mysql_units_writes_increment(juju, MYSQL_APP_NAME)


def evict_pod(pod: Pod) -> None:
    """Evict a pod."""
    if pod.metadata is None:
        return

    logging.info(f"Evicting pod {pod.metadata.name}")
    client = Client()
    eviction = Pod.Eviction(
        metadata=ObjectMeta(
            name=pod.metadata.name,
            namespace=pod.metadata.namespace,
        ),
    )
    client.create(
        obj=eviction,
        name=pod.metadata.name,
    )


def delete_pvs(pod_pvs: list[PersistentVolume]) -> None:
    """Delete the provided PVs."""
    client = Client()

    for pv in pod_pvs:
        logging.info(f"Deleting PV {pv.metadata.name}")
        client.delete(
            res=PersistentVolume,
            name=pv.metadata.name,
            namespace=pv.metadata.namespace,
            grace_period=0,
        )


def delete_pvcs(pod_pvcs: list[PersistentVolumeClaim]) -> None:
    """Delete the provided PVCs."""
    client = Client()

    for pvc in pod_pvcs:
        if pvc.metadata is None:
            continue

        logging.info(f"Deleting PVC {pvc.metadata.name}")
        client.delete(
            res=PersistentVolumeClaim,
            name=pvc.metadata.name,
            namespace=pvc.metadata.namespace,
            grace_period=0,
        )
