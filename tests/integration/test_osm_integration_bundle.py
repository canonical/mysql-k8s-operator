#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import pathlib
import tempfile
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest
from tenacity import AsyncRetrying, RetryError, stop_after_attempt, wait_fixed

from . import markers
from .helpers import (
    execute_queries_on_unit,
    get_server_config_credentials,
    get_unit_address,
    is_relation_joined,
    render_bundle_yaml,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
IMAGE_SOURCE = METADATA["resources"]["mysql-image"]["upstream-source"]
APP_NAME = METADATA["name"]
CLUSTER_NAME = "test_cluster"


# TODO: deploy and relate osm-grafana once it can be use with MySQL Group Replication
@markers.amd64_only  # kafka-k8s charm not available for arm64
async def test_deploy_and_relate_osm_bundle(ops_test: OpsTest, charm) -> None:
    """Test the deployment and relation with OSM bundle."""
    rendered_bundle = render_bundle_yaml(
        "osm_bundle_integration.j2",
        mysql_charm_path=str(pathlib.Path(charm).absolute()),
        mysql_image_source=IMAGE_SOURCE,
    )

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".yaml") as rendered_bundle_file:
        rendered_bundle_file.write(rendered_bundle)
        rendered_bundle_file.flush()

        logger.info("Deploying OSM integration bundle")
        await ops_test.model.deploy(f"local:{rendered_bundle_file.name}", trust=True)

    async with ops_test.fast_forward("60s"):
        # cannot block until "osm-keystone" units are available since they are not
        # registered with ops_test.model.applications (due to the way it's deployed)
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, "mongodb"],
            status="active",
            timeout=1000,
        )
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications["osm-pol"].units) == 1,
            timeout=1000,
        )
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications["kafka"].units) == 1,
            timeout=1000,
        )
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications["zookeeper"].units) == 1,
            timeout=1000,
        )
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications["mongodb"].units) == 1,
            timeout=1000,
        )

        logger.info("Relate kafka and zookeeper")
        await ops_test.model.relate("kafka:zookeeper", "zookeeper:zookeeper")
        await ops_test.model.block_until(
            lambda: is_relation_joined(ops_test, "zookeeper", "zookeeper"),
            timeout=1000,
        )

        await ops_test.model.block_until(
            lambda: ops_test.model.applications["zookeeper"].status == "active",
            timeout=1000,
        )

        logger.info("Relate keystone and mysql")
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

        logger.info("Relate osm-pol and mongo")
        await ops_test.model.relate("osm-pol:mongodb", "mongodb:database")
        await ops_test.model.block_until(
            lambda: is_relation_joined(ops_test, "mongodb", "database"), timeout=1000
        )

        logger.info("Relate osm-pol and kafka")
        await ops_test.model.relate("osm-pol:kafka", "kafka:kafka")
        await ops_test.model.block_until(
            lambda: is_relation_joined(ops_test, "kafka", "kafka"), timeout=1000
        )

        logger.info("Relate osm-pol and mysql")
        await ops_test.model.relate("osm-pol:mysql", f"{APP_NAME}:mysql-root")
        await ops_test.model.block_until(
            lambda: is_relation_joined(ops_test, "mysql", "mysql-root"),
            timeout=1000,
        )


@pytest.mark.abort_on_fail
@markers.amd64_only  # kafka-k8s charm not available for arm64
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
