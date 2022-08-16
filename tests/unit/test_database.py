# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

from charms.mysql.v0.mysql import MySQLDeleteUserForRelationError
from ops.testing import Harness

from charm import MySQLOperatorCharm
from constants import DB_RELATION_NAME

APP_NAME = "mysql-k8s"


class TestDatase(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(MySQLOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.peer_relation_id = self.harness.add_relation("database-peers", "database-peers")
        self.harness.add_relation_unit(self.peer_relation_id, f"{APP_NAME}/1")
        self.database_relation_id = self.harness.add_relation(DB_RELATION_NAME, "app")
        self.harness.add_relation_unit(self.database_relation_id, "app/0")
        self.charm = self.harness.charm

    @patch("mysqlsh_helpers.MySQL.get_mysql_version", return_value="8.0.29-0ubuntu0.20.04.3")
    @patch(
        "mysqlsh_helpers.MySQL.get_cluster_members_addresses",
        return_value={"2.2.2.1:3306", "2.2.2.3:3306", "2.2.2.2:3306"},
    )
    @patch("mysqlsh_helpers.MySQL.get_cluster_primary_address", return_value="2.2.2.2:3306")
    @patch("mysqlsh_helpers.MySQL.create_application_database_and_scoped_user")
    @patch("relations.database.generate_random_password", return_value="super_secure_password")
    def test_database_requested(
        self,
        _generate_random_password,
        _create_application_database_and_scoped_user,
        _get_cluster_primary_address,
        _get_cluster_members_addresses,
        _get_mysql_version,
    ):
        # run start-up events to enable usage of the helper class
        self.harness.set_leader(True)
        self.charm.on.config_changed.emit()

        # confirm that the relation databag is empty
        database_relation_databag = self.harness.get_relation_data(
            self.database_relation_id, self.harness.charm.app
        )
        database_relation = self.charm.model.get_relation(DB_RELATION_NAME)
        app_unit = list(database_relation.units)[0]

        # simulate cluster initialized by editing the flag
        self.harness.update_relation_data(
            self.peer_relation_id, self.charm.app.name, {"units-added-to-cluster": "1"}
        )

        self.assertEqual(database_relation_databag, {})
        self.assertEqual(database_relation.data.get(app_unit), {})
        self.assertEqual(database_relation.data.get(self.charm.unit), {})

        # update the app leader unit data to trigger database_requested event
        self.harness.update_relation_data(
            self.database_relation_id, "app", {"database": "test_db"}
        )

        self.assertEqual(
            database_relation_databag,
            {
                "data": '{"database": "test_db"}',
                "password": "super_secure_password",
                "username": f"relation-{self.database_relation_id}",
                "endpoints": "2.2.2.2:3306",
                "version": "8.0.29-0ubuntu0.20.04.3",
                "read-only-endpoints": "2.2.2.1:3306,2.2.2.3:3306",
            },
        )

        _generate_random_password.assert_called_once()
        _create_application_database_and_scoped_user.assert_called_once()
        _get_cluster_primary_address.assert_called_once()
        _get_cluster_members_addresses.assert_called_once()
        _get_mysql_version.assert_called_once()

    @patch("mysqlsh_helpers.MySQL.delete_user_for_relation")
    def test_database_broken(self, _delete_user_for_relation):
        # run start-up events to enable usage of the helper class
        self.harness.set_leader(True)
        self.charm.on.config_changed.emit()

        self.harness.remove_relation(self.database_relation_id)

        _delete_user_for_relation.assert_called_once_with(self.database_relation_id)

    @patch("mysqlsh_helpers.MySQL.delete_user_for_relation")
    def test_database_broken_failure(self, _delete_user_for_relation):
        # run start-up events to enable usage of the helper class
        self.harness.set_leader(True)
        self.charm.on.config_changed.emit()

        _delete_user_for_relation.side_effect = MySQLDeleteUserForRelationError()

        self.harness.remove_relation(self.database_relation_id)

        _delete_user_for_relation.assert_called_once()
