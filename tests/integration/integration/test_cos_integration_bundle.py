#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import pathlib
import tempfile

import jinja2
import jubilant_backports
import pytest
from jubilant_backports import Juju

from ..helpers_ha import CHARM_METADATA, wait_for_apps_status

logger = logging.getLogger(__name__)

IMAGE_SOURCE = CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]
TIMEOUT = 10 * 60


@pytest.mark.abort_on_fail
def test_deploy_bundle_with_cos_integrations(juju: Juju, charm) -> None:
    """Test COS integrations formed before mysql is allocated and deployed."""
    bundle_template = jinja2.Template(
        pathlib.Path(
            ".",
            "tests",
            "integration",
            "integration",
            "bundle_templates",
            "grafana_agent_integration.j2",
        ).read_text()
    )
    rendered_bundle = bundle_template.render(
        mysql_charm_path=str(pathlib.Path(charm).absolute()), mysql_image_source=IMAGE_SOURCE
    )

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".yaml", dir=".") as rendered_bundle_file:
        rendered_bundle_file.write(rendered_bundle)
        rendered_bundle_file.flush()

        logger.info("Deploying grafana_agent_integration bundle")
        juju.deploy(rendered_bundle_file.name, "grafana-agent-integration", trust=True)

    logger.info("Waiting until mysql-k8s becomes active")
    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, "mysql-k8s"),
        timeout=TIMEOUT,
    )
