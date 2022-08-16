# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of the standard relation."""


import logging

from charms.data_platform_libs.v0.database_provides import (
    DatabaseProvides,
    DatabaseRequestedEvent,
)
from charms.mysql.v0.mysql import (
    MySQLClientError,
    MySQLCreateApplicationDatabaseAndScopedUserError,
    MySQLDeleteUserForRelationError,
    MySQLGetClusterMembersAddressesError,
    MySQLGetMySQLVersionError,
)
from ops.charm import RelationDepartedEvent
from ops.framework import Object
from ops.model import BlockedStatus

from constants import DB_RELATION_NAME, PASSWORD_LENGTH
from utils import generate_random_password

logger = logging.getLogger(__name__)


class DatabaseRelation(Object):
    """Standard database relation class."""

    def __init__(self, charm):
        super().__init__(charm, DB_RELATION_NAME)

        self.charm = charm

        self.database = DatabaseProvides(self.charm, relation_name=DB_RELATION_NAME)
        self.framework.observe(self.database.on.database_requested, self._on_database_requested)

        self.framework.observe(
            self.charm.on[DB_RELATION_NAME].relation_broken, self._on_database_broken
        )

    def _get_or_set_password(self, relation) -> str:
        """Retrieve password from cache or generate a new one.

        Args:
            relation (str): The relation for each the password is cached.

        Returns:
            str: The password.
        """
        if password := relation.data[self.charm.app].get("password"):
            return password
        password = generate_random_password(PASSWORD_LENGTH)
        relation.data[self.charm.app]["password"] = password
        return password

    def _on_database_requested(self, event: DatabaseRequestedEvent):
        """Handle the `database-requested` event."""
        if not self.charm.unit.is_leader():
            return
        # check if cluster is ready and if not, defer
        if not self.charm.cluster_initialized:
            logger.debug("Waiting cluster to be initialized")
            event.defer()
            return

        # get base relation data
        relation_id = event.relation.id
        db_name = event.database
        # user name is derived from the relation id
        db_user = f"relation-{relation_id}"
        db_pass = self._get_or_set_password(event.relation)

        remote_app = event.app.name

        try:
            db_version = self.charm._mysql.get_mysql_version()
            primary_endpoint = self.charm._mysql.get_cluster_primary_address()
            self.database.set_credentials(relation_id, db_user, db_pass)
            self.database.set_endpoints(relation_id, primary_endpoint)
            self.database.set_version(relation_id, db_version)
            # get read only endpoints by removing primary from all members
            read_only_endpoints = sorted(
                self.charm._mysql.get_cluster_members_addresses()
                - {
                    primary_endpoint,
                }
            )

            self.database.set_read_only_endpoints(relation_id, ",".join(read_only_endpoints))
            # TODO:
            # add setup of tls, tls_ca and status
            # add extra roles parsing from relation data
            self.charm._mysql.create_application_database_and_scoped_user(
                db_name, db_user, db_pass, "%", remote_app
            )

            logger.info(f"Created user for app {remote_app}")
        except MySQLCreateApplicationDatabaseAndScopedUserError:
            logger.error(f"Failed to create scoped user for app {remote_app}")
            self.charm.unit.status = BlockedStatus("Failed to create scoped user")
        except MySQLGetMySQLVersionError as e:
            logger.exception("Failed to get MySQL version", exc_info=e)
            self.charm.unit.status = BlockedStatus("Failed to get MySQL version")
        except MySQLGetClusterMembersAddressesError as e:
            logger.exception("Failed to get cluster members", exc_info=e)
            self.charm.unit.status = BlockedStatus("Failed to get cluster members")
        except MySQLClientError as e:
            logger.exception("Failed to get primary", exc_info=e)
            self.charm.unit.status = BlockedStatus("Failed to get primary")

    def _on_database_broken(self, event: RelationDepartedEvent) -> None:
        """Handle the removal of database relation.

        Remove user, keeping database intact.
        """
        if not self.charm.unit.is_leader():
            # run once by the leader
            return

        try:
            relation_id = event.relation.id
            self.charm._mysql.delete_user_for_relation(relation_id)
            logger.info(f"Removed user for relation {relation_id}")
        except MySQLDeleteUserForRelationError:
            logger.error(f"Failed to delete user for relation {relation_id}")
            return
