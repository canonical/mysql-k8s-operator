# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Kubernetes helpers."""

import logging
import socket
from typing import Dict, List, Optional, Tuple

from lightkube import Client
from lightkube.core.exceptions import ApiError
from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Pod, Service
from ops.charm import CharmBase
from tenacity import retry, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)


class KubernetesClientError(Exception):
    """Exception raised when client can't execute."""


class KubernetesHelpers:
    """Kubernetes helpers for service exposure."""

    def __init__(self, charm: CharmBase):
        """Initialize Kubernetes helpers.

        Args:
            charm: a `CharmBase` parent object
        """
        self.pod_name = charm.unit.name.replace("/", "-")
        self.namespace = charm.model.name
        self.app_name = charm.model.app.name
        self.cluster_name = charm.app_peer_data.get("cluster-name")
        self.client = Client()

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

            # Test hack: juju agent 2.9.29 is setting
            # the constraint to the `charm` container only
            # and as a resource `request` instead of a `limit`
            for container in pod.spec.containers:
                if container.name == "charm":
                    if container.resources.requests:
                        return container.resources.requests

            for container in pod.spec.containers:
                if container.name == container_name:
                    return container.resources.limits or {}
            return {}
        except ApiError:
            raise KubernetesClientError

    @retry(stop=stop_after_attempt(10), wait=wait_fixed(1), reraise=True)
    def wait_service_ready(self, service_endpoint: Tuple[str, int]) -> None:
        """Wait for a service to be listening on a given endpoint.

        Args:
            service_endpoint: tuple of service endpoint (ip, port)
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)

        result = sock.connect_ex(service_endpoint)
        sock.close()

        # check if the port is open
        if result != 0:
            logger.debug("Kubernetes service endpoint not ready yet")
            raise KubernetesClientError
        logger.debug("Kubernetes service endpoint ready")
