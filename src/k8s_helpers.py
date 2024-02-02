# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Kubernetes helpers."""

import logging
import socket
import typing
from typing import Dict, List, Optional, Tuple

from lightkube import Client
from lightkube.core.exceptions import ApiError
from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.apps_v1 import StatefulSet
from lightkube.resources.core_v1 import Node, Pod, Service
from tenacity import retry, stop_after_attempt, wait_fixed

from constants import CONTAINER_NAME
from utils import any_memory_to_bytes

logger = logging.getLogger(__name__)

# http{x,core} clutter the logs with debug messages
logging.getLogger("httpcore").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)

SIDECAR_MEM = "250Mi"
SECONDS_DAY = 86400
PROBE_FAILURE_THRESHOLD = 3
PROBE_TIMEOUT_SECONDS = 5

if typing.TYPE_CHECKING:
    from charm import MySQLOperatorCharm


class KubernetesClientError(Exception):
    """Exception raised when client can't execute."""


class KubernetesHelpers:
    """Kubernetes helpers for service exposure."""

    def __init__(self, charm: "MySQLOperatorCharm"):
        """Initialize Kubernetes helpers.

        Args:
            charm: a `CharmBase` parent object
        """
        self.pod_name = charm.unit.name.replace("/", "-")
        self.namespace = charm.model.name
        self.app_name = charm.model.app.name
        self.cluster_name = charm.app_peer_data.get("cluster-name")
        self.client = Client()  # type: ignore

    def create_endpoint_services(self, roles: List[str]) -> None:
        """Create kubernetes service for endpoints.

        Args:
            roles: List of roles to append on the service name
        """
        for role in roles:
            selector = {"cluster-name": self.cluster_name, "role": role}
            service_name = f"{self.app_name}-{role}"
            pod0 = self.client.get(
                res=Pod,
                name=self.app_name + "-0",
                namespace=self.namespace,
            )

            service = Service(
                apiVersion="v1",
                kind="Service",
                metadata=ObjectMeta(
                    namespace=self.namespace,
                    name=service_name,
                    ownerReferences=pod0.metadata.ownerReferences,
                ),
                spec=ServiceSpec(
                    selector=selector,
                    ports=[ServicePort(port=3306, targetPort=3306)],
                    type="ClusterIP",
                ),
            )

            try:
                self.client.create(service)
                logger.info(f"Kubernetes service {service_name} created")
            except ApiError as e:
                if e.status.code == 403:
                    logger.error("Kubernetes service creation failed: `juju trust` needed")
                if e.status.code == 409:
                    logger.warning("Kubernetes service already exists")
                    return
                else:
                    logger.exception("Kubernetes service creation failed: %s", e)
                raise KubernetesClientError

    def delete_endpoint_services(self, roles: List[str]) -> None:
        """Delete kubernetes service for endpoints.

        Args:
            roles: List of roles to append on the service name
        """
        for role in roles:
            service_name = f"{self.app_name}-{role}"

            try:
                self.client.delete(Service, service_name, namespace=self.namespace)
                logger.info(f"Kubernetes service {service_name} deleted")
            except ApiError as e:
                if e.status.code == 403:
                    logger.warning("Kubernetes service deletion failed: `juju trust` needed")
                else:
                    logger.warning("Kubernetes service deletion failed: %s", e)

    def label_pod(self, role: str, pod_name: Optional[str] = None) -> None:
        """Create or update pod labels.

        Args:
            role: role of a given pod (primary or replica)
            pod_name: (optional) name of the pod to label, defaults to the current pod
        """
        try:
            pod = self.client.get(Pod, pod_name or self.pod_name, namespace=self.namespace)

            if not pod.metadata.labels:
                pod.metadata.labels = {}

            if pod.metadata.labels.get("role") == role:
                return

            pod.metadata.labels["cluster-name"] = self.cluster_name
            pod.metadata.labels["role"] = role
            self.client.patch(Pod, pod_name or self.pod_name, pod)
            logger.info(f"Kubernetes pod label {role} created")
        except ApiError as e:
            if e.status.code == 404:
                logger.warning(f"Kubernetes pod {pod_name} not found. Scaling in?")
                return
            if e.status.code == 403:
                logger.error("Kubernetes pod label creation failed: `juju trust` needed")
            else:
                logger.exception("Kubernetes pod label creation failed: %s", e)
            raise KubernetesClientError

    def get_resources_limits(self, container_name: str) -> Dict:
        """Return resources limits for a given container.

        Args:
            container_name: name of the container to get resources limits for
        """
        try:
            pod = self.client.get(Pod, self.pod_name, namespace=self.namespace)

            for container in pod.spec.containers:
                if container.name == container_name:
                    return container.resources.limits or {}
            return {}
        except ApiError:
            raise KubernetesClientError

    def _get_node_name_for_pod(self) -> str:
        """Return the node name for a given pod."""
        try:
            pod = self.client.get(Pod, name=self.pod_name, namespace=self.namespace)
            return pod.spec.nodeName
        except ApiError:
            raise KubernetesClientError

    def get_node_allocable_memory(self) -> int:
        """Return the allocable memory in bytes for a given node."""
        try:
            node = self.client.get(
                Node, name=self._get_node_name_for_pod(), namespace=self.namespace
            )
            return any_memory_to_bytes(node.status.allocatable["memory"])
        except ApiError:
            raise KubernetesClientError

    def get_node_allocable_cpu(self) -> int:
        """Return the allocable cpu count for a given node."""
        try:
            node = self.client.get(
                Node, name=self._get_node_name_for_pod(), namespace=self.namespace
            )
            return any_memory_to_bytes(node.status.allocatable["cpu"])
        except ApiError:
            raise KubernetesClientError

    @retry(stop=stop_after_attempt(60), wait=wait_fixed(1), reraise=True)
    def wait_service_ready(self, service_endpoint: Tuple[str, int]) -> None:
        """Wait for a service to be listening on a given endpoint.

        Args:
            service_endpoint: tuple of service endpoint (ip, port)
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)

        logger.debug("Checking for Kubernetes service endpoint")
        result = sock.connect_ex(service_endpoint)
        sock.close()

        # check if the port is open
        if result != 0:
            logger.debug(f"Kubernetes {service_endpoint=} not ready")
            raise TimeoutError
        logger.debug("Kubernetes service endpoint ready")

    def set_rolling_update_partition(self, partition: int) -> None:
        """Patch the statefulSet's `spec.updateStrategy.rollingUpdate.partition`.

        Args:
            partition: partition to set
        """
        try:
            patch = {"spec": {"updateStrategy": {"rollingUpdate": {"partition": partition}}}}
            self.client.patch(StatefulSet, name=self.app_name, namespace=self.namespace, obj=patch)
            logger.debug(f"Kubernetes statefulset partition set to {partition}")
        except ApiError as e:
            if e.status.code == 403:
                logger.error("Kubernetes statefulset patch failed: `juju trust` needed")
            else:
                logger.exception("Kubernetes statefulset patch failed")
            raise KubernetesClientError

    def init_statefulset_patch(self):
        """Patch the statefulSet's `spec.template.spec` with custom values."""
        try:
            statefulset = self.client.get(
                StatefulSet, name=self.app_name, namespace=self.namespace
            )
            # Default terminationGracePeriodSeconds to 24h
            statefulset.spec.template.spec.terminationGracePeriodSeconds = SECONDS_DAY

            constraints = self.get_resources_limits(CONTAINER_NAME)
            # user set constraints
            workload_mem = constraints.get("memory")
            workload_cpu = constraints.get("cpu")

            for container in statefulset.spec.template.spec.containers:
                if workload_cpu and workload_mem:
                    # both constraints set, use them to patch the statefulSet
                    # and get Guaranteed QoS Class
                    if container.name == "charm":
                        container.resources.limits = container.resources.requests = {
                            "memory": SIDECAR_MEM,
                            "cpu": 0.1,
                        }
                    if container.name == CONTAINER_NAME:
                        # workload container
                        container.resources.limits = container.resources.requests = {
                            "memory": workload_mem,
                            "cpu": workload_cpu,
                        }

                if container.name == CONTAINER_NAME:
                    container.livenessProbe.failureThreshold = PROBE_FAILURE_THRESHOLD
                    container.livenessProbe.timeoutSeconds = PROBE_TIMEOUT_SECONDS

            # always patch init container to get Burstable QoS Class
            init_container = statefulset.spec.template.spec.initContainers[0]
            init_container.resources.limits = init_container.resources.requests = {
                "memory": SIDECAR_MEM,
                "cpu": 0.1,
            }

            self.client.patch(
                StatefulSet, name=self.app_name, namespace=self.namespace, obj=statefulset
            )
            logger.debug(f"Kubernetes statefulset '{self.app_name}' succesffuly patched")
        except ApiError as e:
            if e.status.code == 409:
                logger.warning(
                    "Kubernetes statefulset patch failed: already patched, wait rolling update"
                )
                return
            elif e.status.code == 403:
                logger.critical(
                    f"Application is not trusted. To fix it run `juju trust {self.app_name} --scope=cluster`"
                )
            raise KubernetesClientError

    def is_pod_best_effort(self) -> bool:
        """Return True if the statefulSet's `spec.template.spec` is patched."""
        try:
            pod = self.client.get(Pod, name=self.pod_name, namespace=self.namespace)

            return pod.status.qosClass == "BestEffort"
        except ApiError as e:
            if e.status.code == 403:
                logger.critical(
                    f"Application is not trusted. To fix it run `juju trust {self.app_name} --scope=cluster`"
                )
            raise KubernetesClientError
