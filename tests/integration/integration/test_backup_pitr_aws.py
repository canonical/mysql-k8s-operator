# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
from jubilant_backports import Juju

from .helpers_backups import build_and_deploy_operations, pitr_operations

logging.getLogger("jubilant.wait").setLevel(logging.WARNING)


@pytest.mark.abort_on_fail
def test_build_and_deploy_aws(
    juju: Juju, cloud_configs_aws: tuple[dict[str, str], dict[str, str]], charm
) -> None:
    """Build and deploy for AWS."""
    build_and_deploy_operations(juju, charm, cloud_configs_aws[0], cloud_configs_aws[1])


@pytest.mark.abort_on_fail
def test_pitr_aws(juju: Juju, cloud_configs_aws: tuple[dict[str, str], dict[str, str]]) -> None:
    """Pitr tests."""
    pitr_operations(juju, cloud_configs_aws[0], cloud_configs_aws[1])
