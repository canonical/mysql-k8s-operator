# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from pytest_operator.plugin import OpsTest

from ..helpers import (
    get_cluster_status,
    get_primary_unit,
)
from .high_availability_helpers import (
    ensure_all_units_continuous_writes_incrementing,
    ensure_n_online_mysql_members,
    get_application_name,
    isolate_instance_from_cluster,
    remove_instance_isolation,
    wait_until_units_in_status,
)

logger = logging.getLogger(__name__)

MYSQL_CONTAINER_NAME = "mysql"
MYSQLD_PROCESS_NAME = "mysqld"
TIMEOUT = 40 * 60


async def test_network_cut_affecting_an_instance(
    ops_test: OpsTest, highly_available_cluster, continuous_writes, chaos_mesh, credentials
) -> None:
    """Test for a network cut affecting an instance."""
    mysql_application_name = get_application_name(ops_test, "mysql")
    assert mysql_application_name, "mysql application name is not set"

    logger.info("Ensuring that there are 3 online mysql members")
    assert await ensure_n_online_mysql_members(ops_test, 3), (
        "The deployed mysql application does not have three online nodes"
    )

    logger.info("Ensuring that all instances have incrementing continuous writes")
    await ensure_all_units_continuous_writes_incrementing(ops_test, credentials=credentials)

    mysql_units = ops_test.model.applications[mysql_application_name].units
    primary = await get_primary_unit(ops_test, mysql_units[0], mysql_application_name)

    assert primary is not None, "No primary unit found"

    logger.info(
        f"Creating networkchaos policy to isolate instance {primary.name} from the cluster"
    )
    isolate_instance_from_cluster(ops_test, primary.name)

    remaining_units = [unit for unit in mysql_units if unit.name != primary.name]

    logger.info("Wait until MySQL GR actually detects isolated instance")
    await wait_until_units_in_status(ops_test, [primary], remaining_units[0], "(missing)")
    await wait_until_units_in_status(ops_test, remaining_units, remaining_units[0], "online")

    cluster_status = await get_cluster_status(remaining_units[0])

    isolated_primary_status, isolated_primary_memberrole = [
        (member["status"], member["memberrole"])
        for label, member in cluster_status["defaultreplicaset"]["topology"].items()
        if label == primary.name.replace("/", "-")
    ][0]
    assert isolated_primary_status == "(missing)"
    assert isolated_primary_memberrole == "secondary"

    new_primary = await get_primary_unit(ops_test, remaining_units[0], mysql_application_name)
    assert primary.name != new_primary.name

    logger.info("Ensure all units have incrementing continuous writes")
    await ensure_all_units_continuous_writes_incrementing(
        ops_test, credentials=credentials, mysql_units=remaining_units
    )

    logger.info("Remove networkchaos policy isolating instance from cluster")
    remove_instance_isolation(ops_test)

    async with ops_test.fast_forward():
        logger.info("Wait until returning instance enters recovery")
        await ops_test.model.block_until(
            lambda: primary.workload_status != "active", timeout=TIMEOUT
        )
        logger.info("Wait until returning instance become active")
        await ops_test.model.block_until(
            lambda: primary.workload_status == "active", timeout=TIMEOUT
        )

    logger.info("Wait until all units are online")
    await wait_until_units_in_status(ops_test, mysql_units, mysql_units[0], "online")

    new_cluster_status = await get_cluster_status(mysql_units[0])

    logger.info("Ensure isolated instance is now secondary")
    isolated_primary_status, isolated_primary_memberrole = [
        (member["status"], member["memberrole"])
        for label, member in new_cluster_status["defaultreplicaset"]["topology"].items()
        if label == primary.name.replace("/", "-")
    ][0]
    assert isolated_primary_status == "online"
    assert isolated_primary_memberrole == "secondary"

    logger.info("Ensure there are 3 online mysql members")
    assert await ensure_n_online_mysql_members(ops_test, 3), (
        "The deployed mysql application does not have three online nodes"
    )

    logger.info("Ensure all units have incrementing continuous writes")
    await ensure_all_units_continuous_writes_incrementing(ops_test, credentials=credentials)
