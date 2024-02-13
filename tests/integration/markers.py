# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest

from . import juju_

only_with_juju_secrets = pytest.mark.skipif(
    not juju_.has_secrets, reason="Requires juju version w/secrets"
)
only_without_juju_secrets = pytest.mark.skipif(
    juju_.has_secrets, reason="Requires juju version w/o secrets"
)
