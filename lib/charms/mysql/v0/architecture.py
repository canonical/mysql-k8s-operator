# Copyright 2024 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Library to provide hardware architecture checks for VMs and K8s charms.

The WrongArchitectureWarningCharm class is designed to be used alongside
the is-wrong-architecture helper function, as follows:

```python
from ops import main
from charms.mysql.v0.architecture import WrongArchitectureWarningCharm, is_wrong_architecture

if __name__ == "__main__":
    if is_wrong_architecture():
        main(WrongArchitectureWarningCharm)
```
"""

import logging
import os
import pathlib
import platform

import yaml
from ops.charm import CharmBase
from ops.model import BlockedStatus

# The unique Charmhub library identifier, never change it
LIBID = "827e04542dba4c2a93bdc70ae40afdb1"
LIBAPI = 0
LIBPATCH = 1


logger = logging.getLogger(__name__)


class WrongArchitectureWarningCharm(CharmBase):
    """A fake charm class that only signals a wrong architecture deploy."""

    def __init__(self, *args):
        super().__init__(*args)

        hw_arch = platform.machine()
        self.unit.status = BlockedStatus(
            f"Charm incompatible with {hw_arch} architecture. "
            f"If this app is being refreshed, rollback"
        )
        raise RuntimeError(
            f"Incompatible architecture: this charm revision does not support {hw_arch}. "
            f"If this app is being refreshed, rollback with instructions from Charmhub docs. "
            f"If this app is being deployed for the first time, remove it and deploy it again "
            f"using a compatible revision."
        )


def is_wrong_architecture() -> bool:
    """Checks if charm was deployed on wrong architecture."""
    charm_path = os.environ.get("CHARM_DIR", "")
    manifest_path = pathlib.Path(charm_path, "manifest.yaml")

    if not manifest_path.exists():
        logger.error("Cannot check architecture: manifest file not found in %s", manifest_path)
        return False

    manifest = yaml.safe_load(manifest_path.read_text())

    manifest_archs = []
    for base in manifest["bases"]:
        base_archs = base.get("architectures", [])
        manifest_archs.extend(base_archs)

    hardware_arch = platform.machine()
    if (
        ("amd64" in manifest_archs and hardware_arch == "x86_64")
        or ("arm64" in manifest_archs and hardware_arch == "aarch64")
        or ("s390x" in manifest_archs and hardware_arch == "s390x")
    ):
        logger.debug("Charm architecture matches")
        return False

    logger.error("Charm architecture does not match")
    return True
