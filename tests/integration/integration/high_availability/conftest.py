#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import subprocess
from collections.abc import Generator

import pytest
from jubilant_backports import Juju
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from ...helpers_ha import (
    get_app_leader,
)

MYSQL_TEST_APP_NAME = "mysql-test-app"


@pytest.fixture()
def continuous_writes(juju: Juju) -> Generator:
    """Starts continuous writes to the MySQL cluster for a test and clear the writes at the end."""
    test_app_leader = get_app_leader(juju, MYSQL_TEST_APP_NAME)

    logging.info("Clearing continuous writes")
    juju.run(test_app_leader, "clear-continuous-writes")
    logging.info("Starting continuous writes")
    juju.run(test_app_leader, "start-continuous-writes")

    yield

    logging.info("Clearing continuous writes")
    juju.run(test_app_leader, "clear-continuous-writes")


@pytest.fixture()
def chaos_mesh(juju: Juju) -> Generator:
    """Deploys chaos mesh to the namespace and uninstalls it at the end."""
    logging.info("Deploying chaos mesh")
    deploy_chaos_mesh(juju.model)

    yield

    logging.info("Destroying chaos mesh")
    destroy_chaos_mesh(juju.model)


def deploy_chaos_mesh(namespace: str) -> None:
    """Deploy chaos mesh to the provided namespace."""
    env = os.environ
    env["KUBECONFIG"] = os.path.expanduser("~/.kube/config")

    subprocess.check_output(
        f"tests/integration/integration/high_availability/scripts/deploy_chaos_mesh.sh {namespace}",
        shell=True,
        env=env,
    )

    logging.info("Ensure chaos mesh is ready")
    try:
        for attempt in Retrying(stop=stop_after_delay(5 * 60), wait=wait_fixed(10)):
            with attempt:
                output = subprocess.check_output(
                    f"microk8s.kubectl get pods --namespace {namespace} -l app.kubernetes.io/instance=chaos-mesh".split(),
                    env=env,
                )
                assert output.decode().count("Running") == 4, "Chaos Mesh not ready"

    except RetryError:
        raise Exception("Chaos Mesh pods not found") from None


def destroy_chaos_mesh(namespace: str) -> None:
    """Remove chaos mesh from the provided namespace."""
    env = os.environ
    env["KUBECONFIG"] = os.path.expanduser("~/.kube/config")

    subprocess.check_output(
        f"tests/integration/integration/high_availability/scripts/destroy_chaos_mesh.sh {namespace}",
        shell=True,
        env=env,
    )
