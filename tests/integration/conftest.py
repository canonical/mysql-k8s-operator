#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import pathlib

import pytest
import yaml
from pytest_operator.plugin import OpsTest


@pytest.fixture
def ops_test(ops_test: OpsTest) -> OpsTest:
    if os.environ.get("CI") == "true":
        # Running in GitHub Actions; skip build step
        # (GitHub Actions uses a separate, cached build step. See .github/workflows/ci.yaml)

        async def build_charm(charm_path, bases_index: int = None) -> str:
            charm_path = pathlib.Path(charm_path)
            if bases_index is not None:
                charmcraft_yaml = yaml.safe_load((charm_path / "charmcraft.yaml").read_text())
                assert charmcraft_yaml["type"] == "charm"
                base = charmcraft_yaml["bases"][bases_index]
                # Handle multiple base formats
                # See https://discourse.charmhub.io/t/charmcraft-bases-provider-support/4713
                version = base.get("build-on", [base])[0]["channel"]
                packed_charms = list(charm_path.glob(f"*{version}-amd64.charm"))
            else:
                packed_charms = list(charm_path.glob("*.charm"))
            if len(packed_charms) == 1:
                return f"./{packed_charms[0]}"
            elif len(packed_charms) > 1:
                message = (
                    f"More than one matching .charm file found at {charm_path=}: {packed_charms}."
                )
                if bases_index is None:
                    message += " Specify `bases_index`"
                else:
                    message += " Does charmcraft.yaml contain non-amd64 architecture?"
                raise ValueError(message)
            else:
                raise ValueError(
                    f"Unable to find amd64 .charm file for {bases_index=} at {charm_path=}"
                )

        ops_test.build_charm = build_charm

    return ops_test
