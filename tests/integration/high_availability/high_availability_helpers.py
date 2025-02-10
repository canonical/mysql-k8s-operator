# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import string
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

import kubernetes
import lightkube
import yaml
from juju.model import Model
from juju.unit import Unit
from lightkube import Client
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.apps_v1 import StatefulSet
from lightkube.resources.core_v1 import Endpoints, PersistentVolume, PersistentVolumeClaim, Pod
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, retry, stop_after_attempt, stop_after_delay, wait_fixed

from ..helpers import (
    execute_queries_on_unit,
    generate_random_string,
    get_cluster_status,
    get_primary_unit,
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

logger = logging.getLogger(__name__)


async def get_max_written_value_in_database(
    ops_test: OpsTest, unit: Unit, credentials: dict
) -> int:
    """Retrieve the max written value in the MySQL database.

    Args:
        ops_test: The ops test framework
        unit: The MySQL unit on which to execute queries on
        credentials: The credentials to use to connect to the MySQL database
    """
    unit_address = await get_unit_address(ops_test, unit.name)

    select_max_written_value_sql = [f"SELECT MAX(number) FROM `{DATABASE_NAME}`.`{TABLE_NAME}`;"]

    output = execute_queries_on_unit(
        unit_address=unit_address,
        username=credentials["username"],
        password=credentials["password"],
        queries=select_max_written_value_sql,
    )

    return output[0]


def get_application_name(ops_test: OpsTest, application_name_substring: str) -> Optional[str]:
    """Returns the name of the application with the provided application name.

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
                cluster_status = await get_cluster_status(mysql_unit)
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
    charm,
    check_for_existing_application: bool = True,
    mysql_application_name: str = MYSQL_DEFAULT_APP_NAME,
    num_units: int = 3,
    model: Optional[Model] = None,
    cluster_name: str = CLUSTER_NAME,
) -> str:
    """Deploys and scales the mysql application charm.

    Args:
        ops_test: The ops test framework
        charm: `charm` fixture
        check_for_existing_application: Whether to check for existing mysql applications
            in the model
        mysql_application_name: The name of the mysql application if it is to be deployed
        num_units: The number of units to deploy
        model: The model to deploy the mysql application to
        cluster_name: The name of the mysql cluster
    """
    application_name = get_application_name(ops_test, "mysql")
    if not model:
        model = ops_test.model

    if check_for_existing_application and application_name:
        if len(model.applications[application_name].units) != num_units:
            async with ops_test.fast_forward("60s"):
                await scale_application(ops_test, application_name, num_units)

        return application_name

    config = {"cluster-name": cluster_name, "profile": "testing"}
    resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}

    async with ops_test.fast_forward("60s"):
        await ops_test.model.deploy(
            charm,
            application_name=mysql_application_name,
            config=config,
            resources=resources,
            num_units=num_units,
            base="ubuntu@22.04",
            trust=True,
        )

        await ops_test.model.wait_for_idle(
            apps=[mysql_application_name],
            status="active",
            raise_on_blocked=True,
            timeout=TIMEOUT,
            raise_on_error=False,
        )

        assert len(ops_test.model.applications[mysql_application_name].units) == num_units

    return mysql_application_name


async def deploy_and_scale_application(
    ops_test: OpsTest,
    check_for_existing_application: bool = True,
    test_application_name: str = APPLICATION_DEFAULT_APP_NAME,
) -> str:
    """Deploys and scales the test application charm.

    Args:
        ops_test: The ops test framework
        check_for_existing_application: Whether to check for existing test applications
        test_application_name: Name of test application to be deployed
    """
    application_name = get_application_name(ops_test, test_application_name)

    if check_for_existing_application and application_name:
        if len(ops_test.model.applications[application_name].units) != 1:
            async with ops_test.fast_forward("60s"):
                await scale_application(ops_test, application_name, 1)

        return application_name

    async with ops_test.fast_forward("60s"):
        await ops_test.model.deploy(
            APPLICATION_DEFAULT_APP_NAME,
            application_name=test_application_name,
            num_units=1,
            channel="latest/edge",
            base="ubuntu@22.04",
            config={"sleep_interval": 300},
        )

        await ops_test.model.wait_for_idle(
            apps=[test_application_name],
            status="waiting",
            raise_on_blocked=True,
            timeout=TIMEOUT,
        )

        assert len(ops_test.model.applications[test_application_name].units) == 1

    return test_application_name


async def relate_mysql_and_application(
    ops_test: OpsTest, mysql_application_name: str, application_name: str
) -> None:
    """Relates the mysql and application charms.

    Args:
        ops_test: The ops test framework
        mysql_application_name: The mysql charm application name
        application_name: The continuous writes test charm application name
    """
    if is_relation_joined(
        ops_test,
        "database",
        "database",
        application_one=mysql_application_name,
        application_two=application_name,
    ):
        return

    await ops_test.model.relate(
        f"{application_name}:database", f"{mysql_application_name}:database"
    )
    await ops_test.model.block_until(
        lambda: is_relation_joined(
            ops_test,
            "database",
            "database",
            application_one=mysql_application_name,
            application_two=application_name,
        )
    )

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
        " ".join([
            "tests/integration/high_availability/scripts/deploy_chaos_mesh.sh",
            namespace,
        ]),
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


async def send_signal_to_pod_container_process(
    model_name: str, unit_name: str, container_name: str, process: str, signal_code: str
) -> None:
    """Send the specified signal to a pod container process.

    Args:
        model_name: The juju model name
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
        model_name,
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
    credentials: dict,
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
    primary_address = await get_unit_address(ops_test, primary.name)

    value = generate_random_string(255)
    insert_value_sql = [
        f"CREATE DATABASE IF NOT EXISTS `{database_name}`",
        f"CREATE TABLE IF NOT EXISTS `{database_name}`.`{table_name}` (id varchar(255), primary key (id))",
        f"INSERT INTO `{database_name}`.`{table_name}` (id) VALUES ('{value}')",
    ]

    execute_queries_on_unit(
        primary_address,
        credentials["username"],
        credentials["password"],
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

                    output = execute_queries_on_unit(
                        unit_address,
                        credentials["username"],
                        credentials["password"],
                        select_value_sql,
                    )
                    assert output[0] == value
    except RetryError:
        assert False, "Cannot query inserted data from all units"

    return value


async def clean_up_database_and_table(
    ops_test: OpsTest, database_name: str, table_name: str, credentials: dict
) -> None:
    """Cleans the database and table created by insert_data_into_mysql_and_validate_replication.

    Args:
        ops_test: The ops test framework
        database_name: The name of the database to drop
        table_name: The name of the table to drop
        credentials: The credentials to use to connect to the MySQL database
    """
    mysql_application_name = get_application_name(ops_test, "mysql")

    assert mysql_application_name, "MySQL application not found"

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]

    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
    primary_address = await get_unit_address(ops_test, primary.name)

    clean_up_database_and_table_sql = [
        f"DROP TABLE IF EXISTS `{database_name}`.`{table_name}`",
        f"DROP DATABASE IF EXISTS `{database_name}`",
    ]

    execute_queries_on_unit(
        primary_address,
        credentials["username"],
        credentials["password"],
        clean_up_database_and_table_sql,
        commit=True,
    )


async def ensure_all_units_continuous_writes_incrementing(
    ops_test: OpsTest,
    credentials: dict,
    mysql_units: Optional[List[Unit]] = None,
    mysql_application_name: Optional[str] = None,
) -> None:
    """Ensure that continuous writes is incrementing on all units.

    Also, ensure that all continuous writes up to the max written value is available
    on all units (ensure that no committed data is lost).
    """
    if not mysql_application_name:
        mysql_application_name = get_application_name(ops_test, "mysql")

    if not mysql_units:
        mysql_units = ops_test.model.applications[mysql_application_name].units

    primary = await get_primary_unit(ops_test, mysql_units[0], mysql_application_name)

    assert primary, "Primary unit not found"

    last_max_written_value = await get_max_written_value_in_database(
        ops_test, primary, credentials
    )

    async with ops_test.fast_forward(fast_interval="15s"):
        for unit in mysql_units:
            for attempt in Retrying(stop=stop_after_delay(15 * 60), wait=wait_fixed(10)):
                with attempt:
                    # ensure the max written value is incrementing (continuous writes is active)
                    max_written_value = await get_max_written_value_in_database(
                        ops_test, unit, credentials
                    )
                    logger.info(f"{max_written_value=} on unit {unit.name}")
                    assert (
                        max_written_value > last_max_written_value
                    ), "Continuous writes not incrementing"

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
    cluster_status = await get_cluster_status(online_unit)

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


def get_pod(ops_test: OpsTest, unit_name: str) -> Pod:
    """Retrieve the PVs of a pod."""
    client = lightkube.Client()
    return client.get(
        res=Pod, namespace=ops_test.model.info.name, name=unit_name.replace("/", "-")
    )


def get_pod_pvcs(pod: Pod) -> list[PersistentVolumeClaim]:
    """Get a pod's PVCs."""
    if pod.spec is None:
        return []

    client = lightkube.Client()
    pod_pvcs = []

    for volume in pod.spec.volumes:
        if volume.persistentVolumeClaim is None:
            continue

        pvc_name = volume.persistentVolumeClaim.claimName
        pod_pvcs.append(
            client.get(
                res=PersistentVolumeClaim,
                name=pvc_name,
                namespace=pod.metadata.namespace,
            )
        )

    return pod_pvcs


def get_pod_pvs(pod: Pod) -> list[PersistentVolume]:
    """Get a pod's PVs."""
    if pod.spec is None:
        return []

    pod_pvs = []
    client = lightkube.Client()
    for pv in client.list(res=PersistentVolume, namespace=pod.metadata.namespace):
        if pv.spec.claimRef.name.endswith(pod.metadata.name):
            pod_pvs.append(pv)
    return pod_pvs


def evict_pod(pod: Pod) -> None:
    """Evict a pod."""
    if pod.metadata is None:
        return

    logger.info(f"Evicting pod {pod.metadata.name}")
    client = lightkube.Client()
    eviction = Pod.Eviction(
        metadata=ObjectMeta(name=pod.metadata.name, namespace=pod.metadata.namespace),
    )
    client.create(eviction, name=str(pod.metadata.name))


def delete_pvs(pvs: list[PersistentVolume]) -> None:
    """Delete the provided PVs."""
    for pv in pvs:
        logger.info(f"Deleting PV {pv.spec.claimRef.name}")
        client = lightkube.Client()
        client.delete(
            PersistentVolume,
            pv.metadata.name,
            namespace=pv.spec.claimRef.namespace,
            grace_period=0,
        )


def delete_pvcs(pvcs: list[PersistentVolumeClaim]) -> None:
    """Delete the provided PVCs."""
    for pvc in pvcs:
        if pvc.metadata is None:
            continue

        logger.info(f"Deleting PVC {pvc.metadata.name}")
        client = lightkube.Client()
        client.delete(
            PersistentVolumeClaim,
            pvc.metadata.name,
            namespace=pvc.metadata.namespace,
            grace_period=0,
        )


def delete_pod(ops_test: OpsTest, unit: Unit) -> None:
    """Delete the provided pod."""
    pod_name = unit.name.replace("/", "-")
    subprocess.run(
        [
            "microk8s.kubectl",
            "-n",
            ops_test.model.info.name,
            "delete",
            "pod",
            pod_name,
        ],
        check=True,
    )


def get_endpoint_addresses(ops_test: OpsTest, endpoint_name: str) -> list[str]:
    """Retrieve the addresses selected by a K8s endpoint."""
    client = lightkube.Client()
    endpoint = client.get(
        Endpoints,
        namespace=ops_test.model.info.name,
        name=endpoint_name,
    )

    return [address.ip for subset in endpoint.subsets for address in subset.addresses]
