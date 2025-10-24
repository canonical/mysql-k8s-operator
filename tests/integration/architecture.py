# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import subprocess

architecture = subprocess.check_output(
    ["dpkg", "--print-architecture"],
    text=True,
).strip()
