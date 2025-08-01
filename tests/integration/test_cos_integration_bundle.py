#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import tempfile
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from . import markers
from .helpers import render_bundle_yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
IMAGE_SOURCE = METADATA["resources"]["mysql-image"]["upstream-source"]
TIMEOUT = 10 * 60


# TODO: remove after https://github.com/canonical/grafana-agent-k8s-operator/issues/309 fixed
@markers.amd64_only
@pytest.mark.abort_on_fail
async def test_deploy_and_relate_cos_bundle(ops_test: OpsTest, charm) -> None:
    """Test the deployment and relation with COS bundle."""
    rendered_bundle = render_bundle_yaml(
        "cos_bundle_integration.j2",
        mysql_charm_path=str(Path(charm).absolute()),
        mysql_image_source=IMAGE_SOURCE,
    )

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".yaml") as rendered_bundle_file:
        rendered_bundle_file.write(rendered_bundle)
        rendered_bundle_file.flush()

        logger.info("Deploying COS integration bundle")
        await ops_test.model.deploy(f"local:{rendered_bundle_file.name}", trust=True)

    logger.info("Waiting until mysql-k8s becomes active")
    await ops_test.model.wait_for_idle(
        apps=["mysql-k8s"],
        status="active",
        raise_on_blocked=True,
        timeout=TIMEOUT,
    )
