# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Kubernetes helpers."""

import logging
from typing import List, Optional

from lightkube import Client
from lightkube.core.exceptions import ApiError
from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Pod, Service
from ops.charm import CharmBase

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

            service = Service(
                apiVersion="v1",
                kind="Service",
                metadata=ObjectMeta(
                    namespace=self.namespace,
                    name=service_name,
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
