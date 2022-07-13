#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.helpers import (
    execute_queries_on_unit,
    get_server_config_credentials,
    get_unit_address,
    scale_application,
)

logger = logging.getLogger(__name__)


METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
CLUSTER_NAME = "test_cluster"
DATABASE_APP_NAME = "mysql"
OSM_KEYSTONE_APP_NAME = "osm-keystone"
KFP_API_APP_NAME = "kfp-api"


@pytest.mark.order(1)
@pytest.mark.abort_on_fail
@pytest.mark.legacy_mysql_tests
async def test_osm_keystone_bundle_mysql(ops_test: OpsTest) -> None:
    """Deploy the osm keystone bundle to test the legacy 'mysql' relation.

    Args:
        ops_test: The ops test framework
    """
    async with ops_test.fast_forward():
        # Build and deploy the mysql charm
        charm = await ops_test.build_charm(".")
        resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}
        config = {
            "user": "keystone",
            "database": "keystone",
        }
        await ops_test.model.deploy(
            charm,
            resources=resources,
            config=config,
            application_name=DATABASE_APP_NAME,
            num_units=3,
        )

        await ops_test.model.wait_for_idle(
            apps=[DATABASE_APP_NAME],
            status="active",
            raise_on_blocked=True,
            timeout=1000,
            wait_for_exact_units=3,
        )
        assert len(ops_test.model.applications[DATABASE_APP_NAME].units) == 3
        for unit in ops_test.model.applications[DATABASE_APP_NAME].units:
            assert unit.workload_status == "active"

        # Build and deploy the osm-keystone charm
        osm_keystone_resources = {
            "keystone-image": "opensourcemano/keystone:testing-daily",
        }
        await ops_test.model.deploy(
            "osm-keystone",
            channel="edge",
            application_name=OSM_KEYSTONE_APP_NAME,
            num_units=1,
            trust=True,
            resources=osm_keystone_resources,
        )
        await ops_test.model.wait_for_idle(
            apps=[OSM_KEYSTONE_APP_NAME],
            status="blocked",
            raise_on_blocked=False,
            timeout=1000,
            wait_for_exact_units=1,
        )

        # Relate the mysql charm with the osm-keystone charm
        await ops_test.model.relate(f"{OSM_KEYSTONE_APP_NAME}:db", f"{DATABASE_APP_NAME}:mysql")
        await ops_test.model.wait_for_idle(
            apps=[OSM_KEYSTONE_APP_NAME, DATABASE_APP_NAME],
            status="active",
            raise_on_blocked=False,
            timeout=1000,
        )

        # Ensure that the keystone database exists and tables within it exist
        # (the keystone app migrated successfully)
        show_databases_sql = [
            "SHOW DATABASES",
        ]
        get_count_keystone_tables_sql = [
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'keystone'",
        ]

        random_unit = ops_test.model.applications[DATABASE_APP_NAME].units[0]
        server_config_credentials = await get_server_config_credentials(random_unit)

        for unit in ops_test.model.applications[DATABASE_APP_NAME].units:
            unit_address = await get_unit_address(ops_test, unit.name)

            output = await execute_queries_on_unit(
                unit_address,
                server_config_credentials["username"],
                server_config_credentials["password"],
                show_databases_sql,
            )
            assert "keystone" in output

            output = await execute_queries_on_unit(
                unit_address,
                server_config_credentials["username"],
                server_config_credentials["password"],
                get_count_keystone_tables_sql,
            )
            assert output[0] > 0

        # Scale down all applications
        await scale_application(ops_test, OSM_KEYSTONE_APP_NAME, 0)
        await scale_application(ops_test, DATABASE_APP_NAME, 0)

        await ops_test.model.remove_application(OSM_KEYSTONE_APP_NAME, block_until_done=True)
        await ops_test.model.remove_application(DATABASE_APP_NAME, block_until_done=True)


@pytest.mark.order(2)
@pytest.mark.abort_on_fail
@pytest.mark.legacy_mysql_tests
async def test_kubeflow_mysql(ops_test: OpsTest) -> None:
    async with ops_test.fast_forward():
        # Build and deploy the mysql charm
        charm = await ops_test.build_charm(".")
        resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}
        config = {
            "user": "mysql",
            "database": "mlpipeline",
        }
        await ops_test.model.deploy(
            charm,
            resources=resources,
            config=config,
            application_name=DATABASE_APP_NAME,
            num_units=1,
        )

        await ops_test.model.wait_for_idle(
            apps=[DATABASE_APP_NAME],
            status="active",
            raise_on_blocked=True,
            timeout=1000,
            wait_for_exact_units=1,
        )
        assert len(ops_test.model.applications[DATABASE_APP_NAME].units) == 1
        assert ops_test.model.applications[DATABASE_APP_NAME].units[0].workload_status == "active"

        # Deploy the kfp-api charm and relate it with mysql
        await ops_test.model.deploy(
            entity_url="kfp-api", application_name=KFP_API_APP_NAME, trust=True
        )
        await ops_test.model.relate(
            f"{KFP_API_APP_NAME}:mysql",
            f"{DATABASE_APP_NAME}:mysql",
        )

        # Deploy minio and relate it to kfp-api
        minio_config = {"access-key": "minio", "secret-key": "minio-secret-key"}
        await ops_test.model.deploy(entity_url="minio", config=minio_config)
        await ops_test.model.relate(
            f"{KFP_API_APP_NAME}:object-storage",
            "minio:object-storage",
        )

        # Deploy kfp-viz and relate it to kfp-api
        await ops_test.model.deploy(entity_url="kfp-viz")
        await ops_test.model.relate(
            f"{KFP_API_APP_NAME}:kfp-viz",
            "kfp-viz:kfp-viz",
        )

        # Wait till all services are active
        await ops_test.model.wait_for_idle(
            apps=[DATABASE_APP_NAME, KFP_API_APP_NAME, "minio", "kfp-viz"],
            status="active",
            timeout=1000,
        )

        # Ensure that the mlpipeline database exists and tables within it exist
        show_databases_sql = [
            "SHOW DATABASES",
        ]
        get_count_mlpipeline_tables = [
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mlpipeline'",
        ]

        random_unit = ops_test.model.applications[DATABASE_APP_NAME].units[0]
        server_config_credentials = await get_server_config_credentials(random_unit)

        for unit in ops_test.model.applications[DATABASE_APP_NAME].units:
            unit_address = await get_unit_address(ops_test, unit.name)

            output = await execute_queries_on_unit(
                unit_address,
                server_config_credentials["username"],
                server_config_credentials["password"],
                show_databases_sql,
            )
            assert "mlpipeline" in output

            output = await execute_queries_on_unit(
                unit_address,
                server_config_credentials["username"],
                server_config_credentials["password"],
                get_count_mlpipeline_tables,
            )
            assert output[0] > 0

        # Scale down all applications
        await scale_application(ops_test, "minio", 0)
        await scale_application(ops_test, "kfp-viz", 0)
        await scale_application(ops_test, KFP_API_APP_NAME, 0)
        await scale_application(ops_test, DATABASE_APP_NAME, 0)

        await ops_test.model.remove_application("minio", block_until_done=True)
        await ops_test.model.remove_application("kfp-viz", block_until_done=True)
        await ops_test.model.remove_application(KFP_API_APP_NAME, block_until_done=True)
        await ops_test.model.remove_application(DATABASE_APP_NAME, block_until_done=True)
