# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import uuid

import jubilant_backports
import pytest
from pytest_operator.plugin import OpsTest

from constants import SERVER_CONFIG_USERNAME

from . import architecture, juju_
from .integration.high_availability.high_availability_helpers import get_application_name

logging.getLogger("jubilant.wait").setLevel(logging.WARNING)


@pytest.fixture(scope="session")
def charm():
    # Return str instead of pathlib.Path since python-libjuju's model.deploy(), juju deploy, and
    # juju bundle files expect local charms to begin with `./` or `/` to distinguish them from
    # Charmhub charms.
    return f"./mysql-k8s_ubuntu@22.04-{architecture.architecture}.charm"


@pytest.fixture(scope="function")
async def credentials(ops_test: OpsTest):
    """Return the credentials for the MySQL cluster."""
    logging.info("Getting credentials for the MySQL cluster")
    mysql_app_name = get_application_name(ops_test, "mysql-k8s")
    unit = ops_test.model.applications[mysql_app_name].units[0]
    credentials = await juju_.run_action(unit, "get-password", username=SERVER_CONFIG_USERNAME)

    yield credentials


@pytest.fixture(scope="session")
def cloud_configs_aws() -> tuple[dict[str, str], dict[str, str]]:
    configs = {
        "endpoint": os.getenv("AWS_ENDPOINT_URL", "https://s3.amazonaws.com"),
        "bucket": "data-charms-testing",
        "path": f"mysql-k8s/{uuid.uuid4()}",
        "region": "us-east-1",
    }
    credentials = {
        "access-key": os.environ["AWS_ACCESS_KEY"],
        "secret-key": os.environ["AWS_SECRET_KEY"],
    }
    return configs, credentials


@pytest.fixture(scope="session")
def cloud_configs_gcp() -> tuple[dict[str, str], dict[str, str]]:
    configs = {
        "endpoint": "https://storage.googleapis.com",
        "bucket": "data-charms-testing",
        "path": f"mysql-k8s/{uuid.uuid4()}",
        "region": "us-east-1",
    }
    credentials = {
        "access-key": os.environ["GCP_ACCESS_KEY"],
        "secret-key": os.environ["GCP_SECRET_KEY"],
    }
    return configs, credentials


@pytest.fixture(scope="module")
def juju(request: pytest.FixtureRequest):
    """Pytest fixture that wraps :meth:`jubilant.with_model`.

    This adds command line parameter ``--keep-models`` (see help for details).
    """
    model = request.config.getoption("--model")
    keep_models = bool(request.config.getoption("--keep-models"))

    if model:
        juju = jubilant_backports.Juju(model=model)  # type: ignore
        yield juju
        log = juju.debug_log(limit=1000)
    else:
        with jubilant_backports.temp_model(keep=keep_models) as juju:
            yield juju
            log = juju.debug_log(limit=1000)

    if request.session.testsfailed:
        print(log, end="")
