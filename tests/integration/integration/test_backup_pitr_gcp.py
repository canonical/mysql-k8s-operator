# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from jubilant_backports import Juju

from .helpers_backups import build_and_deploy_operations, pitr_operations


@pytest.mark.abort_on_fail
def test_build_and_deploy_gcp(
    juju: Juju, cloud_configs_gcp: tuple[dict[str, str], dict[str, str]], charm
) -> None:
    """Build and deploy for GCP."""
    build_and_deploy_operations(juju, charm, cloud_configs_gcp[0], cloud_configs_gcp[1])


@pytest.mark.abort_on_fail
def test_pitr_gcp(juju: Juju, cloud_configs_gcp: tuple[dict[str, str], dict[str, str]]) -> None:
    """Pitr tests."""
    pitr_operations(juju, cloud_configs_gcp[0], cloud_configs_gcp[1])
