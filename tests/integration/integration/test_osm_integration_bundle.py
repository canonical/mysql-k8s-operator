#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
import logging

import jubilant_backports
import pytest
from jubilant_backports import Juju
from tenacity import RetryError, Retrying, stop_after_attempt, wait_fixed

from constants import ROOT_USERNAME

from .. import markers
from ..helpers_ha import (
    CHARM_METADATA,
    MINUTE_SECS,
    execute_queries_on_unit,
    get_app_units,
    get_mysql_server_credentials,
    get_unit_address,
    wait_for_apps_status,
)

logger = logging.getLogger(__name__)

APP_NAME = CHARM_METADATA["name"]
CLUSTER_NAME = "test_cluster"
TIMEOUT = 20 * MINUTE_SECS


# TODO: deploy and relate osm-grafana once it can be use with MySQL Group Replication
@markers.juju3
@markers.amd64_only  # kafka-k8s charm not available for arm64
def test_deploy_and_relate_osm_bundle(juju: Juju, charm) -> None:
    """Test the deployment and relation with osm bundle with mysql replacing mariadb."""
    resources = {"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]}
    config = {
        "mysql-root-interface-user": "keystone",
        "mysql-root-interface-database": "keystone",
        "profile": "testing",
    }

    logger.info("Deploying mysql")
    juju.deploy(
        charm,
        APP_NAME,
        resources=resources,
        config=config,
        num_units=1,
        base="ubuntu@22.04",
        trust=True,
    )

    logger.info("Deploying osm-keystone")
    juju.deploy(
        "osm-keystone",
        channel="latest/beta",
        base="ubuntu@22.04",
        resources={"keystone-image": "opensourcemano/keystone:testing-daily"},
    )

    logger.info("Deploying osm-pol")
    juju.deploy(
        "osm-pol",
        "osm-pol",
        channel="latest/beta",
        resources={"image": "opensourcemano/pol:testing-daily"},
        trust=True,
        base="ubuntu@22.04",
    )

    logger.info("Deploying kafka")
    juju.deploy(
        "kafka-k8s",
        "kafka",
        trust=True,
        channel="latest/stable",
        base="ubuntu@20.04",
    )

    logger.info("Deploying zookeeper")
    juju.deploy(
        "zookeeper-k8s",
        "zookeeper",
        channel="latest/stable",
        base="ubuntu@20.04",
    )

    logger.info("Deploying mongodb")
    juju.deploy(
        "mongodb-k8s",
        "mongodb",
        channel="6/stable",
        base="ubuntu@22.04",
        trust=True,
    )

    # Wait for mysql and mongodb to become active
    logger.info("Waiting for mysql and mongodb to become active")
    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, APP_NAME, "mongodb"),
        timeout=TIMEOUT,
    )

    logger.info("Waiting for all apps to have units")
    juju.wait(
        ready=lambda status: (
            len(status.apps["osm-pol"].units) >= 1
            and len(status.apps["kafka"].units) >= 1
            and len(status.apps["zookeeper"].units) >= 1
            and len(status.apps["mongodb"].units) >= 1
        ),
        timeout=TIMEOUT,
    )

    logger.info("Relate kafka and zookeeper")
    juju.integrate("kafka:zookeeper", "zookeeper:zookeeper")

    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, "zookeeper"),
        timeout=TIMEOUT,
    )

    logger.info("Relate keystone and mysql")
    juju.integrate("osm-keystone:db", f"{APP_NAME}:mysql-root")

    logger.info("Waiting for keystone and mysql to settle")
    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, APP_NAME, "osm-keystone"),
        error=wait_for_apps_status(jubilant_backports.any_error, APP_NAME, "osm-keystone"),
        timeout=TIMEOUT,
    )

    logger.info("Relate osm-pol and mongo")
    juju.integrate("osm-pol:mongodb", "mongodb:database")

    logger.info("Relate osm-pol and kafka")
    juju.integrate("osm-pol:kafka", "kafka:kafka")

    logger.info("Relate osm-pol and mysql")
    juju.integrate("osm-pol:mysql", f"{APP_NAME}:mysql-root")


@pytest.mark.abort_on_fail
@markers.juju3
@markers.amd64_only  # kafka-k8s charm not available for arm64
def test_osm_pol_operations(juju: Juju) -> None:
    """Test the existence of databases and tables created by osm-pol's migrations."""
    show_databases_sql = [
        "SHOW DATABASES",
    ]
    get_count_pol_tables = [
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'pol'",
    ]

    app_units = get_app_units(juju, APP_NAME)
    db_unit = app_units[0]
    server_config_credentials = get_mysql_server_credentials(juju, db_unit, ROOT_USERNAME)

    # Retry until osm-pol runs migrations since it is not possible to wait_for_idle
    # as osm-pol throws intermittent pod errors (due to being a podspec charm)
    try:
        for attempt in Retrying(stop=stop_after_attempt(30), wait=wait_fixed(30)):
            with attempt:
                for unit_name in app_units:
                    unit_address = get_unit_address(juju, APP_NAME, unit_name)

                    # test that the `keystone` and `pol` databases exist
                    output = execute_queries_on_unit(
                        unit_address,
                        server_config_credentials["username"],
                        server_config_credentials["password"],
                        show_databases_sql,
                    )
                    assert "keystone" in output
                    assert "pol" in output

                    # test that osm-pol successfully creates tables
                    output = execute_queries_on_unit(
                        unit_address,
                        server_config_credentials["username"],
                        server_config_credentials["password"],
                        get_count_pol_tables,
                    )
                    assert output[0] > 0
    except RetryError:
        assert False
