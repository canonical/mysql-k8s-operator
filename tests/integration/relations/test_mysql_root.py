#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest
from tenacity import AsyncRetrying, RetryError, stop_after_attempt, wait_fixed

from ..helpers import (
    execute_queries_on_unit,
    get_server_config_credentials,
    get_unit_address,
    is_relation_joined,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
CLUSTER_NAME = "test_cluster"


# TODO: deploy and relate osm-grafana once it can be use with MySQL Group Replication
@pytest.mark.group(1)
async def test_deploy_and_relate_osm_bundle(ops_test: OpsTest) -> None:
    """Test the deployment and relation with osm bundle with mysql replacing mariadb."""
    async with ops_test.fast_forward("60s"):
        charm = await ops_test.build_charm(".")
        resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}
        config = {
            "mysql-root-interface-user": "keystone",
            "mysql-root-interface-database": "keystone",
            "profile": "testing",
        }

        osm_pol_resources = {
            "image": "opensourcemano/pol:testing-daily",
        }

        await asyncio.gather(
            ops_test.model.deploy(
                charm,
                application_name=APP_NAME,
                resources=resources,
                config=config,
                num_units=3,
                series="jammy",
                trust=True,
            ),
            # Deploy the osm-keystone charm
            # (using ops_test.juju instead of ops_test.deploy as the latter does
            # not correctly deploy with the correct resources)
            ops_test.juju(
                "deploy",
                "--channel=latest/edge",
                "--trust",
                "--resource",
                "keystone-image=opensourcemano/keystone:testing-daily",
                "osm-keystone",
                "osm-keystone",
            ),
            ops_test.model.deploy(
                "osm-pol",
                application_name="osm-pol",
                channel="latest/candidate",
                resources=osm_pol_resources,
            ),
            ops_test.model.deploy(
                "charmed-osm-kafka-k8s",
                application_name="osm-kafka",
            ),
            ops_test.model.deploy("charmed-osm-zookeeper-k8s", application_name="osm-zookeeper"),
            ops_test.model.deploy("charmed-osm-mongodb-k8s", application_name="osm-mongodb"),
        )

        # cannot block until "osm-keystone" units are available since they are not
        # registered with ops_test.model.applications (due to the way it's deployed)
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications[APP_NAME].units) == 3,
            timeout=1000,
        )
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications["osm-pol"].units) == 1,
            timeout=1000,
        )
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications["osm-kafka"].units) == 1,
            timeout=1000,
        )
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications["osm-zookeeper"].units) == 1,
            timeout=1000,
        )
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications["osm-mongodb"].units) == 1,
            timeout=1000,
        )

        await ops_test.model.relate("osm-kafka:zookeeper", "osm-zookeeper:zookeeper")
        await ops_test.model.block_until(
            lambda: is_relation_joined(ops_test, "zookeeper", "zookeeper"),
            timeout=1000,
        )

        # osm-zookeeper is never `active` long enough (15 seconds is necessary),
        # it constantly changes state `active`<>`maintenance`:
        # > osm-zookeeper/0 [idle] maintenance: Sending Zookeeper configuration
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, "osm-kafka", "osm-mongodb"],
            status="active",
            raise_on_blocked=True,
            timeout=1000,
        )
        await ops_test.model.block_until(
            lambda: ops_test.model.applications["osm-zookeeper"].status == "active",
            timeout=1000,
        )

        await ops_test.model.relate("osm-keystone:db", f"{APP_NAME}:mysql-root")
        await ops_test.model.block_until(
            lambda: is_relation_joined(ops_test, "db", "mysql-root"), timeout=1000
        )
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, "osm-keystone"],
            status="active",
            # osm-keystone is initially in blocked status
            raise_on_blocked=False,
            timeout=1000,
        )

        await ops_test.model.relate("osm-pol:mongodb", "osm-mongodb:mongo")
        await ops_test.model.block_until(
            lambda: is_relation_joined(ops_test, "mongodb", "mongo"), timeout=1000
        )

        await ops_test.model.relate("osm-pol:kafka", "osm-kafka:kafka")
        await ops_test.model.block_until(
            lambda: is_relation_joined(ops_test, "kafka", "kafka"), timeout=1000
        )

        await ops_test.model.relate("osm-pol:mysql", f"{APP_NAME}:mysql-root")
        await ops_test.model.block_until(
            lambda: is_relation_joined(ops_test, "mysql", "mysql-root"),
            timeout=1000,
        )


@pytest.mark.abort_on_fail
@pytest.mark.group(1)
async def test_osm_pol_operations(ops_test: OpsTest) -> None:
    """Test the existence of databases and tables created by osm-pol's migrations."""
    show_databases_sql = [
        "SHOW DATABASES",
    ]
    get_count_pol_tables = [
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'pol'",
    ]

    db_unit = ops_test.model.applications[APP_NAME].units[0]
    server_config_credentials = await get_server_config_credentials(db_unit)

    # Retry until osm-pol runs migrations since it is not possible to wait_for_idle
    # as osm-pol throws intermittent pod errors (due to being a podspec charm)
    try:
        async for attempt in AsyncRetrying(stop=stop_after_attempt(30), wait=wait_fixed(30)):
            with attempt:
                for unit in ops_test.model.applications[APP_NAME].units:
                    unit_address = await get_unit_address(ops_test, unit.name)

                    # test that the `keystone` and `pol` databases exist
                    output = await execute_queries_on_unit(
                        unit_address,
                        server_config_credentials["username"],
                        server_config_credentials["password"],
                        show_databases_sql,
                    )
                    assert "keystone" in output
                    assert "pol" in output

                    # test that osm-pol successfully creates tables
                    output = await execute_queries_on_unit(
                        unit_address,
                        server_config_credentials["username"],
                        server_config_credentials["password"],
                        get_count_pol_tables,
                    )
                    assert output[0] > 0
    except RetryError:
        assert False
