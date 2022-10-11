# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest

from high_availability_helpers import get_application_name
from pytest_operator.plugin import OpsTest


@pytest.fixture
async def continuous_writes(ops_test: OpsTest):
    """Starts continuous writes to the MySQL cluster for a test and clear the writes at the end."""
    application_name = await get_application_name(ops_test, "application")

    application_unit = ops_test.model.applications[application_name].units[0]

    start_writes_action = await application_unit.run_action("start-continuous-writes")
    await start_writes_action.wait()

    yield

    clear_writes_action = await application_unit.run_action("clear-continuous-writes")
    await clear_writes_action.wait()
