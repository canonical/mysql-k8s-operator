# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import PropertyMock

import pytest
from ops import JujuVersion
from pytest_mock import MockerFixture


@pytest.fixture
def with_juju_secrets(mocker: MockerFixture):
    """Ensure that JujuVersion.has_secrets returns True."""
    mocker.patch.object(JujuVersion, "has_secrets", new_callable=PropertyMock).return_value = True


@pytest.fixture
def without_juju_secrets(mocker: MockerFixture):
    """Ensure that JujuVersion.has_secrets returns False."""
    mocker.patch.object(JujuVersion, "has_secrets", new_callable=PropertyMock).return_value = False
