# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time

import lightkube
from lightkube.resources.core_v1 import Pod
from pytest_operator.plugin import OpsTest

from ..helpers import (
    get_primary_unit,
)
from .high_availability_helpers import (
    clean_up_database_and_table,
    ensure_all_units_continuous_writes_incrementing,
    ensure_n_online_mysql_members,
    get_application_name,
    insert_data_into_mysql_and_validate_replication,
)

logger = logging.getLogger(__name__)

TIMEOUT = 15 * 60


async def test_kill_primary_check_reelection(
    ops_test: OpsTest, highly_available_cluster, continuous_writes, credentials
) -> None:
    """Test to kill the primary under load and ensure re-election of primary."""
    mysql_application_name = get_application_name(ops_test, "mysql")
    assert mysql_application_name, "mysql application not found"

    await ensure_all_units_continuous_writes_incrementing(ops_test, credentials=credentials)

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
    primary_name = primary.name

    # kill the primary pod
    client = lightkube.Client()
    client.delete(Pod, primary.name.replace("/", "-"), namespace=ops_test.model.info.name)

    time.sleep(60)

    async with ops_test.fast_forward("60s"):
        # wait for model to stabilize, k8s will re-create the killed pod
        await ops_test.model.wait_for_idle(
            apps=[mysql_application_name],
            status="active",
            raise_on_blocked=True,
            timeout=TIMEOUT,
            idle_period=30,
        )

        # ensure a new primary was elected
        mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
        new_primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
        new_primary_name = new_primary.name

        assert primary_name != new_primary_name

        # wait (and retry) until the killed pod is back online in the mysql cluster
        assert await ensure_n_online_mysql_members(
            ops_test, 3
        ), "Old primary has not come back online after being killed"

    await ensure_all_units_continuous_writes_incrementing(ops_test, credentials=credentials)

    database_name, table_name = "test-kill-primary-check-reelection", "data"
    await insert_data_into_mysql_and_validate_replication(
        ops_test, database_name, table_name, credentials
    )
    await clean_up_database_and_table(ops_test, database_name, table_name, credentials)
