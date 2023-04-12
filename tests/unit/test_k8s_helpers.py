# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import MagicMock, patch

from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Pod, Service
from ops.charm import CharmBase
from ops.testing import Harness

from k8s_helpers import KubernetesHelpers


class _FakeCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.app_peer_data = {"cluster-name": "test-cluster"}


class TestK8sHelpers(unittest.TestCase):
    def setUp(self) -> None:
        # mock generic sync client to avoid search to ~/.kube/config
        self.patcher = patch("lightkube.core.client.GenericSyncClient")
        self.mock_k8s_client = self.patcher.start()
        self.harness = Harness(_FakeCharm, meta="name: test-charm")
        self.harness.begin()
        self.k8s_helpers = KubernetesHelpers(self.harness.charm)

    def tearDown(self) -> None:
        # stop patching
        self.patcher.stop()

    @patch("lightkube.Client.create")
    def test_create_endpoint_service(self, _create):
        self.k8s_helpers.create_endpoint_services(["role1"])
        _create.assert_called_once_with(
            Service(
                apiVersion="v1",
                kind="Service",
                metadata=ObjectMeta(
                    namespace=self.harness.charm.model.name,
                    name=f"{self.harness.charm.model.app.name}-role1",
                ),
                spec=ServiceSpec(
                    selector={
                        "cluster-name": self.harness.charm.app_peer_data.get("cluster-name"),
                        "role": "role1",
                    },
                    ports=[ServicePort(port=3306, targetPort=3306)],
                    type="ClusterIP",
                ),
            )
        )

    @patch("lightkube.Client.delete")
    def test_delete_endpoint_service(self, _delete):
        self.k8s_helpers.delete_endpoint_services(["role2"])
        _delete.assert_called_once_with(
            Service,
            f"{self.harness.charm.model.app.name}-role2",
            namespace=self.harness.charm.model.name,
        )

    @patch("lightkube.Client.get")
    @patch("lightkube.Client.patch")
    def test_label_pod(self, _patch, _get):
        pod = MagicMock()
        pod.name = self.harness.charm.unit.name.replace("/", "-")
        _get.return_value = pod
        self.k8s_helpers.label_pod("role1")
        _patch.assert_called_once_with(Pod, pod.name, pod)

    @patch("lightkube.Client.get")
    def test_get_resources_limit(self, _get):
        pod = MagicMock()
        container = MagicMock()
        container.resources.limits = {"memory": "2Gi"}
        container.name = "mysql"
        pod.spec.containers = [container]
        _get.return_value = pod
        self.assertEqual(
            self.k8s_helpers.get_resources_limits(container_name="mysql"), {"memory": "2Gi"}
        )
