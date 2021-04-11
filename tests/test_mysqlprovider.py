# Copyright 2021 Canonical Ltd
# See LICENSE file for licensing details.

import json
import unittest

from ops.testing import Harness
from fakes import MySQLCharm, METADATA, PROVIDER_META, CONFIG, CONFIG_YAML


class TestMySQLProvider(unittest.TestCase):
    def setup_harness(self, config, meta):
        config_yaml = CONFIG_YAML.format(**config)
        meta_yaml = PROVIDER_META.format(**meta)
        self.harness = Harness(MySQLCharm, meta=meta_yaml, config=config_yaml)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin()

    def test_databases_are_created_when_requested(self):
        config = CONFIG.copy()
        meta = METADATA.copy()
        self.setup_harness(config, meta)

        requested_database = ["mysql_database"]
        json_request = json.dumps(requested_database)
        consumer_data = {"databases": json_request}

        rel_id = self.harness.add_relation("database", "consumer")
        data = self.harness.get_relation_data(
            rel_id, self.harness.model.app.name
        )
        self.assertDictEqual(data, {})
        self.harness.add_relation_unit(rel_id, "consumer/0")
        self.harness.update_relation_data(rel_id, "consumer", consumer_data)
        data = self.harness.get_relation_data(
            rel_id, self.harness.model.app.name
        )
        databases = json.loads(data["databases"])
        self.assertListEqual(databases, requested_database)
