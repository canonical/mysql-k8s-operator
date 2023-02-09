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
from ops.framework import Object

logger = logging.getLogger(__name__)


class KubernetesClientError(Exception):
    """Exception raised when client can't execute."""


class KubernetesHelpers(Object):
    """Kubernetes helpers for service exposure."""

    def __init__(self, charm: CharmBase):
        """Initialize Kubernetes helpers.

        Args:
            charm: a `CharmBase` parent object
        """
        super().__init__(charm, "kubernetes-helpers")
        self.charm = charm
        self.pod_name = charm.unit.name.replace("/", "-", -1)
        self.namespace = self.model.name
        self.client = Client()

    def create_endpoint_services(self, roles: List[str]) -> None:
        """Create kubernetes service for endpoints.

        Args:
            roles: List of roles to append on the service name
        """
        for role in roles:
            selector = {"cluster-name": self.charm.app_peer_data.get("cluster-name"), "role": role}
            service_name = f"{self.model.app.name}-{role}"

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
            except ApiError as e:
                if e.status.code == 403:
                    logger.error("Kubernetes service creation failed: `juju trust` needed")
                else:
                    logger.error("Kubernetes service creation failed: %s", e)
                raise KubernetesClientError()
            else:
                logger.info(f"Kubernetes service {service_name} created")

    def label_pod(self, role: str, pod_name: Optional[str] = None) -> None:
        """Create or update pod labels.

        Args:
            role: role of a given pod (primary or replica)
            pod_name: (optional) name of the pod to label, defaults to the current pod
        """
        pod = self.client.get(Pod, pod_name or self.pod_name, namespace=self.namespace)

        if not pod.metadata.labels:
            pod.metadata.labels = {}

        pod.metadata.labels["cluster-name"] = self.charm.app_peer_data.get("cluster-name")
        pod.metadata.labels["role"] = role

        try:
            self.client.patch(Pod, pod_name or self.pod_name, pod)
        except ApiError as e:
            if e.status.code == 403:
                logger.error("Kubernetes pod label creation failed: `juju trust` needed")
            else:
                logger.error("Kubernetes pod label creation failed: %s", e)
            raise KubernetesClientError()
        else:
            logger.info(f"Kubernetes pod label {role} created")
