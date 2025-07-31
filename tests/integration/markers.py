# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest

from . import architecture, juju_

only_with_juju_secrets = pytest.mark.skipif(
    not juju_.has_secrets, reason="Requires juju version w/secrets"
)
only_without_juju_secrets = pytest.mark.skipif(
    juju_.has_secrets, reason="Requires juju version w/o secrets"
)
juju3 = pytest.mark.skipif(juju_.juju_major_version < 3, reason="Requires juju 3+")
amd64_only = pytest.mark.skipif(
    architecture.architecture != "amd64", reason="Requires amd64 architecture"
)
arm64_only = pytest.mark.skipif(
    architecture.architecture != "arm64", reason="Requires arm64 architecture"
)
s390x_only = pytest.mark.skipif(
    architecture.architecture != "s390x", reason="Requires s390x architecture"
)
