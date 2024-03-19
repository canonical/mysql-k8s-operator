# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import string
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

import kubernetes
import yaml
from juju.unit import Unit
from lightkube import Client
from lightkube.resources.apps_v1 import StatefulSet
from pytest_operator.plugin import OpsTest
from tenacity import (
    RetryError,
    Retrying,
    retry,
    stop_after_attempt,
    stop_after_delay,
    wait_fixed,
)

from ..helpers import (
    execute_queries_on_unit,
    generate_random_string,
    get_cluster_status,
    get_primary_unit,
    get_server_config_credentials,
    get_unit_address,
    is_relation_joined,
    scale_application,
)

# Copied these values from high_availability.application_charm.src.charm
DATABASE_NAME = "continuous_writes_database"
TABLE_NAME = "data"

CLUSTER_NAME = "test_cluster"
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
MYSQL_DEFAULT_APP_NAME = METADATA["name"]
APPLICATION_DEFAULT_APP_NAME = "mysql-test-app"
TIMEOUT = 15 * 60

mysql_charm, application_charm = None, None

logger = logging.getLogger(__name__)


async def get_max_written_value_in_database(ops_test: OpsTest, unit: Unit) -> int:
    """Retrieve the max written value in the MySQL database.

    Args:
        ops_test: The ops test framework
        unit: The MySQL unit on which to execute queries on
    """
    server_config_credentials = await get_server_config_credentials(unit)
    unit_address = await get_unit_address(ops_test, unit.name)

    select_max_written_value_sql = [f"SELECT MAX(number) FROM `{DATABASE_NAME}`.`{TABLE_NAME}`;"]

    output = await execute_queries_on_unit(
        unit_address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        select_max_written_value_sql,
    )

    return output[0]


def get_application_name(ops_test: OpsTest, application_name_substring: str) -> str:
    """Returns the name of the application witt the provided application name.

    This enables us to retrieve the name of the deployed application in an existing model.

    Note: if multiple applications with the application name exist,
    the first one found will be returned.
    """
    for application in ops_test.model.applications:
        if application_name_substring in application:
            return application

    return None


async def ensure_n_online_mysql_members(
    ops_test: OpsTest, number_online_members: int, mysql_units: Optional[List[Unit]] = None
) -> bool:
    """Waits until N mysql cluster members are online.

    Args:
        ops_test: The ops test framework
        number_online_members: Number of online members to wait for
        mysql_units: Expected online mysql units
    """
    mysql_application = get_application_name(ops_test, "mysql")

    if not mysql_units:
        mysql_units = ops_test.model.applications[mysql_application].units
    mysql_unit = mysql_units[0]

    try:
        for attempt in Retrying(stop=stop_after_delay(5 * 60), wait=wait_fixed(10)):
            with attempt:
                cluster_status = await get_cluster_status(ops_test, mysql_unit)
                online_members = [
                    label
                    for label, member in cluster_status["defaultreplicaset"]["topology"].items()
                    if member["status"] == "online" and not member.get("instanceerrors")
                ]
                assert len(online_members) == number_online_members
                return True
    except RetryError:
        return False


async def deploy_and_scale_mysql(
    ops_test: OpsTest,
    check_for_existing_application: bool = True,
    mysql_application_name: str = MYSQL_DEFAULT_APP_NAME,
    num_units: int = 3,
) -> str:
    """Deploys and scales the mysql application charm.

    Args:
        ops_test: The ops test framework
        check_for_existing_application: Whether to check for existing mysql applications
            in the model
        mysql_application_name: The name of the mysql application if it is to be deployed
        num_units: The number of units to deploy
    """
    application_name = get_application_name(ops_test, "mysql")

    if check_for_existing_application and application_name:
        if len(ops_test.model.applications[application_name].units) != num_units:
            async with ops_test.fast_forward("60s"):
                await scale_application(ops_test, application_name, num_units)

        return application_name

    global mysql_charm
    if not mysql_charm:
        charm = await ops_test.build_charm(".")
        # Cache the built charm to avoid rebuilding it between tests
        mysql_charm = charm

    config = {"cluster-name": CLUSTER_NAME, "profile": "testing"}
    resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}

    async with ops_test.fast_forward("60s"):
        await ops_test.model.deploy(
            mysql_charm,
            application_name=mysql_application_name,
            config=config,
            resources=resources,
            num_units=num_units,
            series="jammy",
            trust=True,
        )

        await ops_test.model.wait_for_idle(
            apps=[mysql_application_name],
            status="active",
            raise_on_blocked=True,
            timeout=TIMEOUT,
        )

        assert len(ops_test.model.applications[mysql_application_name].units) == num_units

    return mysql_application_name


async def deploy_and_scale_application(ops_test: OpsTest) -> str:
    """Deploys and scales the test application charm.

    Args:
        ops_test: The ops test framework
    """
    application_name = get_application_name(ops_test, APPLICATION_DEFAULT_APP_NAME)

    if application_name:
        if len(ops_test.model.applications[application_name].units) != 1:
            async with ops_test.fast_forward("60s"):
                await scale_application(ops_test, application_name, 1)

        return application_name

    async with ops_test.fast_forward("60s"):
        await ops_test.model.deploy(
            APPLICATION_DEFAULT_APP_NAME,
            application_name=APPLICATION_DEFAULT_APP_NAME,
            num_units=1,
            channel="latest/edge",
        )

        await ops_test.model.wait_for_idle(
            apps=[APPLICATION_DEFAULT_APP_NAME],
            status="waiting",
            raise_on_blocked=True,
            timeout=TIMEOUT,
        )

        assert len(ops_test.model.applications[APPLICATION_DEFAULT_APP_NAME].units) == 1

    return APPLICATION_DEFAULT_APP_NAME


async def relate_mysql_and_application(
    ops_test: OpsTest, mysql_application_name: str, application_name: str
) -> None:
    """Relates the mysql and application charms.

    Args:
        ops_test: The ops test framework
        mysql_application_name: The mysql charm application name
        application_name: The continuous writes test charm application name
    """
    if is_relation_joined(ops_test, "database", "database"):
        return

    await ops_test.model.relate(
        f"{application_name}:database", f"{mysql_application_name}:database"
    )
    await ops_test.model.block_until(lambda: is_relation_joined(ops_test, "database", "database"))

    await ops_test.model.wait_for_idle(
        apps=[mysql_application_name, application_name],
        status="active",
        raise_on_blocked=True,
        timeout=TIMEOUT,
    )


def deploy_chaos_mesh(namespace: str) -> None:
    """Deploy chaos mesh to the provided namespace.

    Args:
        ops_test: The ops test framework
        namespace: The namespace to deploy chaos mesh to
    """
    env = os.environ
    env["KUBECONFIG"] = os.path.expanduser("~/.kube/config")
    logger.info("Deploying Chaos Mesh")

    subprocess.check_output(
        " ".join(
            [
                "tests/integration/high_availability/scripts/deploy_chaos_mesh.sh",
                namespace,
            ]
        ),
        shell=True,
        env=env,
    )
    logger.info("Ensure chaos mesh is ready")
    try:
        for attempt in Retrying(stop=stop_after_delay(5 * 60), wait=wait_fixed(10)):
            with attempt:
                output = subprocess.check_output(
                    f"microk8s.kubectl get pods --namespace {namespace} -l app.kubernetes.io/instance=chaos-mesh".split(),
                    env=env,
                )
                assert output.decode().count("Running") == 4, "Chaos Mesh not ready"

    except RetryError:
        raise Exception("Chaos Mesh pods not found")


def destroy_chaos_mesh(namespace: str) -> None:
    """Remove chaos mesh from the provided namespace.

    Args:
        ops_test: The ops test framework
        namespace: The namespace to deploy chaos mesh to
    """
    env = os.environ
    env["KUBECONFIG"] = os.path.expanduser("~/.kube/config")

    subprocess.check_output(
        f"tests/integration/high_availability/scripts/destroy_chaos_mesh.sh {namespace}",
        shell=True,
        env=env,
    )


async def high_availability_test_setup(ops_test: OpsTest) -> Tuple[str, str]:
    """Run the set up for high availability tests.

    Args:
        ops_test: The ops test framework
    """
    mysql_application_name = await deploy_and_scale_mysql(ops_test)
    application_name = await deploy_and_scale_application(ops_test)

    await relate_mysql_and_application(ops_test, mysql_application_name, application_name)

    return mysql_application_name, application_name


async def send_signal_to_pod_container_process(
    ops_test: OpsTest, unit_name: str, container_name: str, process: str, signal_code: str
) -> None:
    """Send the specified signal to a pod container process.

    Args:
        ops_test: The ops test framework
        unit_name: The name of the unit to send signal to
        container_name: The name of the container to send signal to
        process: The name of the process to send signal to
        signal_code: The code of the signal to send
    """
    kubernetes.config.load_kube_config()

    pod_name = unit_name.replace("/", "-")

    send_signal_command = f"pkill --signal {signal_code} -f {process}"
    response = kubernetes.stream.stream(
        kubernetes.client.api.core_v1_api.CoreV1Api().connect_get_namespaced_pod_exec,
        pod_name,
        ops_test.model.info.name,
        container=container_name,
        command=send_signal_command.split(),
        stdin=False,
        stdout=True,
        stderr=True,
        tty=False,
        _preload_content=False,
    )
    response.run_forever(timeout=5)

    assert (
        response.returncode == 0
    ), f"Failed to send {signal_code} signal, unit={unit_name}, container={container_name}, process={process}"


async def get_process_stat(
    ops_test: OpsTest, unit_name: str, container_name: str, process: str
) -> str:
    """Retrieve the STAT column of a process on a pod container.

    Args:
        ops_test: The ops test framework
        unit_name: The name of the unit for the process
        container_name: The name of the container for the process
        process: The name of the process to get the STAT for
    """
    get_stat_commands = [
        "ssh",
        "--container",
        container_name,
        unit_name,
        f"ps -eo comm,stat | grep {process} | awk '{{print $2}}'",
    ]
    return_code, stat, _ = await ops_test.juju(*get_stat_commands)

    assert (
        return_code == 0
    ), f"Failed to get STAT, unit_name={unit_name}, container_name={container_name}, process={process}"

    return stat


async def insert_data_into_mysql_and_validate_replication(
    ops_test: OpsTest,
    database_name: str,
    table_name: str,
    mysql_units: Optional[List[Unit]] = None,
    mysql_application_substring: Optional[str] = "mysql",
) -> str:
    """Inserts data into the mysql cluster and validates its replication.

    database_name: The name of the database to create
    table_name: The name of the table to create and insert data into
    """
    mysql_application_name = get_application_name(ops_test, mysql_application_substring)

    if not mysql_units:
        mysql_units = ops_test.model.applications[mysql_application_name].units

    primary = await get_primary_unit(ops_test, mysql_units[0], mysql_application_name)

    # insert some data into the new primary and ensure that the writes get replicated
    server_config_credentials = await get_server_config_credentials(primary)
    primary_address = await get_unit_address(ops_test, primary.name)

    value = generate_random_string(255)
    insert_value_sql = [
        f"CREATE DATABASE IF NOT EXISTS `{database_name}`",
        f"CREATE TABLE IF NOT EXISTS `{database_name}`.`{table_name}` (id varchar(255), primary key (id))",
        f"INSERT INTO `{database_name}`.`{table_name}` (id) VALUES ('{value}')",
    ]

    await execute_queries_on_unit(
        primary_address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        insert_value_sql,
        commit=True,
    )

    select_value_sql = [
        f"SELECT id FROM `{database_name}`.`{table_name}` WHERE id = '{value}'",
    ]

    try:
        for attempt in Retrying(stop=stop_after_delay(5 * 60), wait=wait_fixed(10)):
            with attempt:
                for unit in mysql_units:
                    unit_address = await get_unit_address(ops_test, unit.name)

                    output = await execute_queries_on_unit(
                        unit_address,
                        server_config_credentials["username"],
                        server_config_credentials["password"],
                        select_value_sql,
                    )
                    assert output[0] == value
    except RetryError:
        assert False, "Cannot query inserted data from all units"

    return value


async def clean_up_database_and_table(
    ops_test: OpsTest, database_name: str, table_name: str
) -> None:
    """Cleans the database and table created by insert_data_into_mysql_and_validate_replication.

    Args:
        ops_test: The ops test framework
        database_name: The name of the database to drop
        table_name: The name of the table to drop
    """
    mysql_application_name = get_application_name(ops_test, "mysql")

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]

    server_config_credentials = await get_server_config_credentials(mysql_unit)

    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
    primary_address = await get_unit_address(ops_test, primary.name)

    clean_up_database_and_table_sql = [
        f"DROP TABLE IF EXISTS `{database_name}`.`{table_name}`",
        f"DROP DATABASE IF EXISTS `{database_name}`",
    ]

    await execute_queries_on_unit(
        primary_address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        clean_up_database_and_table_sql,
        commit=True,
    )


async def ensure_all_units_continuous_writes_incrementing(
    ops_test: OpsTest, mysql_units: Optional[List[Unit]] = None
) -> None:
    """Ensure that continuous writes is incrementing on all units.

    Also, ensure that all continuous writes up to the max written value is available
    on all units (ensure that no committed data is lost).
    """
    mysql_application_name = get_application_name(ops_test, "mysql")

    if not mysql_units:
        mysql_units = ops_test.model.applications[mysql_application_name].units

    primary = await get_primary_unit(ops_test, mysql_units[0], mysql_application_name)

    last_max_written_value = await get_max_written_value_in_database(ops_test, primary)

    select_all_continuous_writes_sql = [f"SELECT * FROM `{DATABASE_NAME}`.`{TABLE_NAME}`"]
    server_config_credentials = await get_server_config_credentials(mysql_units[0])

    async with ops_test.fast_forward():
        for attempt in Retrying(stop=stop_after_delay(15 * 60), wait=wait_fixed(10)):
            with attempt:
                # ensure that all units are up to date (including the previous primary)
                for unit in mysql_units:
                    unit_address = await get_unit_address(ops_test, unit.name)

                    # ensure the max written value is incrementing (continuous writes is active)
                    max_written_value = await get_max_written_value_in_database(ops_test, unit)
                    assert (
                        max_written_value > last_max_written_value
                    ), "Continuous writes not incrementing"

                    # ensure that the unit contains all values up to the max written value
                    all_written_values = await execute_queries_on_unit(
                        unit_address,
                        server_config_credentials["username"],
                        server_config_credentials["password"],
                        select_all_continuous_writes_sql,
                    )
                    for number in range(1, max_written_value):
                        assert (
                            number in all_written_values
                        ), f"Missing {number} in database for unit {unit.name}"

                    last_max_written_value = max_written_value


def isolate_instance_from_cluster(ops_test: OpsTest, unit_name: str) -> None:
    """Apply a NetworkChaos file to use chaos-mesh to simulate a network cut."""
    with tempfile.NamedTemporaryFile(dir=os.getenv("HOME")) as temp_file:
        with open(
            "tests/integration/high_availability/manifests/chaos_network_loss.yml", "r"
        ) as chaos_network_loss_file:
            template = string.Template(chaos_network_loss_file.read())
            chaos_network_loss = template.substitute(
                namespace=ops_test.model.info.name,
                pod=unit_name.replace("/", "-"),
            )

            temp_file.write(str.encode(chaos_network_loss))
            temp_file.flush()

        env = os.environ
        env["KUBECONFIG"] = os.path.expanduser("~/.kube/config")

        try:
            subprocess.check_output(["microk8s.kubectl", "apply", "-f", temp_file.name], env=env)
        except subprocess.CalledProcessError as e:
            logger.error(e.output)
            logger.error(e.stderr)
            raise


def remove_instance_isolation(ops_test: OpsTest) -> None:
    """Delete the NetworkChaos that is isolating the primary unit of the cluster."""
    env = os.environ
    env["KUBECONFIG"] = os.path.expanduser("~/.kube/config")
    subprocess.check_output(
        f"microk8s.kubectl -n {ops_test.model.info.name} delete networkchaos network-loss-primary",
        shell=True,
        env=env,
    )


@retry(
    stop=stop_after_attempt(10),
    wait=wait_fixed(30),
)
async def wait_until_units_in_status(
    ops_test: OpsTest, units_to_check: List[Unit], online_unit: Unit, status: str
) -> None:
    """Waits until all units specified are in a given status, or timeout occurs."""
    cluster_status = await get_cluster_status(ops_test, online_unit)

    for unit in units_to_check:
        assert (
            cluster_status["defaultreplicaset"]["topology"][unit.name.replace("/", "-")]["status"]
            == status
        )


async def ensure_process_not_running(
    ops_test: OpsTest, unit_name: str, container_name: str, process: str
) -> None:
    """Ensure that the provided process is not running on the unit container.

    Args:
        ops_test: The ops test framework
        unit_name: The name of the unit to ensure the process is not running
        container_name: The name of the container to ensure the process is not running
        process: The name of the process to ensure is not running
    """
    get_pid_commands = ["ssh", "--container", container_name, unit_name, "pgrep", "-x", process]
    return_code, pid, _ = await ops_test.juju(*get_pid_commands)

    assert (
        return_code != 0
    ), f"Process {process} is still running with pid {pid} on unit {unit_name}, container {container_name}"


def get_sts_partition(ops_test: OpsTest, app_name: str) -> int:
    client = Client()  # type: ignore
    statefulset = client.get(res=StatefulSet, namespace=ops_test.model.info.name, name=app_name)
    return statefulset.spec.updateStrategy.rollingUpdate.partition  # type: ignore
