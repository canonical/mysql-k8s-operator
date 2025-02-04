# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import lightkube
from lightkube.resources.core_v1 import Pod
from pytest_operator.plugin import OpsTest

from ..helpers import (
    scale_application,
)
from .high_availability_helpers import (
    clean_up_database_and_table,
    get_application_name,
    insert_data_into_mysql_and_validate_replication,
)

logger = logging.getLogger(__name__)

MYSQL_CONTAINER_NAME = "mysql"
MYSQLD_PROCESS_NAME = "mysqld"
TIMEOUT = 40 * 60


async def test_single_unit_pod_delete(
    ops_test: OpsTest, highly_available_cluster, credentials
) -> None:
    """Delete the pod in a single unit deployment and write data to new pod."""
    mysql_application_name = get_application_name(ops_test, "mysql")
    assert mysql_application_name, "mysql application name is not set"

    logger.info("Scale mysql application to 1 unit that is active")
    async with ops_test.fast_forward("60s"):
        await scale_application(ops_test, mysql_application_name, 1)
    unit = ops_test.model.applications[mysql_application_name].units[0]
    assert unit.workload_status == "active"

    logger.info("Delete pod for the the mysql unit")
    client = lightkube.Client()
    client.delete(Pod, unit.name.replace("/", "-"), namespace=ops_test.model.info.name)

    logger.info("Wait for a new pod to be created by k8s")
    async with ops_test.fast_forward("60s"):
        await ops_test.model.wait_for_idle(
            apps=[mysql_application_name],
            status="active",
            raise_on_blocked=True,
            timeout=TIMEOUT,
            idle_period=30,
        )

    logger.info("Write data to unit and verify that data was written")
    database_name, table_name = "test-single-pod-delete", "data"
    await insert_data_into_mysql_and_validate_replication(
        ops_test,
        database_name=database_name,
        table_name=table_name,
        credentials=credentials,
        mysql_application_substring="mysql-k8s",
    )
    await clean_up_database_and_table(ops_test, database_name, table_name, credentials)
