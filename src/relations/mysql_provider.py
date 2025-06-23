# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of the standard relation."""

import logging
import socket
import typing

from charms.data_platform_libs.v0.data_interfaces import DatabaseProvides, DatabaseRequestedEvent
from charms.mysql.v0.mysql import (
    MySQLCreateApplicationDatabaseAndScopedUserError,
    MySQLDeleteUserError,
    MySQLDeleteUsersForRelationError,
    MySQLGetMySQLVersionError,
    MySQLGrantPrivilegesToUserError,
    MySQLRemoveRouterFromMetadataError,
)
from ops.charm import PebbleReadyEvent, RelationBrokenEvent, RelationDepartedEvent
from ops.framework import Object
from ops.model import ActiveStatus, BlockedStatus

from constants import CONTAINER_NAME, CONTAINER_RESTARTS, DB_RELATION_NAME, PASSWORD_LENGTH, PEER
from k8s_helpers import KubernetesClientError
from utils import dotappend, generate_random_password

logger = logging.getLogger(__name__)

if typing.TYPE_CHECKING:
    from charm import MySQLOperatorCharm


class MySQLProvider(Object):
    """Standard database relation class."""

    def __init__(self, charm: "MySQLOperatorCharm") -> None:
        super().__init__(charm, DB_RELATION_NAME)

        self.charm = charm

        self.database = DatabaseProvides(self.charm, relation_name=DB_RELATION_NAME)
        self.framework.observe(self.database.on.database_requested, self._on_database_requested)

        self.framework.observe(
            self.charm.on[DB_RELATION_NAME].relation_broken, self._on_database_broken
        )
        self.framework.observe(
            self.charm.on[DB_RELATION_NAME].relation_departed,
            self._on_database_provides_relation_departed,
        )

        self.framework.observe(self.charm.on[PEER].relation_changed, self._configure_endpoints)
        self.framework.observe(self.charm.on.leader_elected, self._configure_endpoints)
        self.framework.observe(self.charm.on.mysql_pebble_ready, self._on_mysql_pebble_ready)
        self.framework.observe(self.charm.on.update_status, self._on_update_status)

    # =============
    # Helpers
    # =============

    def _get_or_set_password(self, relation) -> str:
        """Retrieve password from cache or generate a new one.

        Args:
            relation (str): The relation for each the password is cached.

        Returns:
            str: The password.
        """
        if password := self.database.fetch_my_relation_field(relation.id, "password"):
            return password
        password = generate_random_password(PASSWORD_LENGTH)
        self.database.update_relation_data(relation.id, {"password": password})
        return password

    def _get_username(self, relation_id: int, legacy: bool = False) -> str:
        """Generate a unique username for the relation using the model uuid and the relation id.

        Args:
            relation_id (int): The relation id.
            legacy (bool): If True, generate a username without the model uuid.

        Returns:
            str: A valid unique username (limited to 26 characters)
        """
        if legacy:
            return f"relation-{relation_id}"
        return f"relation-{relation_id}_{self.model.uuid.replace('-', '')}"[:26]

    # =============
    # Handlers
    # =============

    def _on_database_requested(self, event: DatabaseRequestedEvent) -> None:
        """Handle the `database-requested` event."""
        if not self.charm.unit.is_leader():
            return
        container = self.charm.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            logger.debug("Container is not ready")
            event.defer()
            return
        # check if cluster is ready and if not, defer
        if not self.charm.cluster_initialized:
            logger.debug("Waiting cluster to be initialized")
            event.defer()
            return

        # get base relation data
        relation_id = event.relation.id
        db_name = event.database
        extra_user_roles = []
        if event.extra_user_roles:
            extra_user_roles = event.extra_user_roles.split(",")
        # user name is derived from the relation id
        db_user = self._get_username(relation_id)
        db_pass = self._get_or_set_password(event.relation)

        remote_app = event.app.name

        try:
            # make sure pods are labeled before adding service
            self.charm._mysql.update_endpoints(DB_RELATION_NAME)

            # create k8s services for endpoints
            self.charm.k8s_helpers.create_endpoint_services(["primary", "replicas"])

            primary_endpoint = dotappend(socket.getfqdn(f"{self.charm.app.name}-primary"))
            replicas_endpoint = dotappend(socket.getfqdn(f"{self.charm.app.name}-replicas"))

            db_version = self.charm._mysql.get_mysql_version()

            # wait for endpoints to be ready
            self.charm.k8s_helpers.wait_service_ready((primary_endpoint, 3306))

            if "mysqlrouter" in extra_user_roles:
                self.charm._mysql.create_application_database_and_scoped_user(
                    db_name,
                    db_user,
                    db_pass,
                    "%",
                    # MySQL Router charm does not need a new database
                    create_database=False,
                )
                self.charm._mysql.grant_privileges_to_user(
                    db_user, "%", ["ALL PRIVILEGES"], with_grant_option=True
                )
            else:
                # TODO:
                # add setup of tls, tls_ca and status
                # add extra roles parsing from relation data
                self.charm._mysql.create_application_database_and_scoped_user(
                    db_name, db_user, db_pass, "%"
                )

            # Set relation data
            self.database.set_endpoints(relation_id, f"{primary_endpoint}:3306")
            self.database.set_read_only_endpoints(relation_id, f"{replicas_endpoint}:3306")
            self.database.set_credentials(relation_id, db_user, db_pass)
            self.database.set_version(relation_id, db_version)
            self.database.set_database(relation_id, db_name)

            logger.info(f"Created user for app {remote_app}")
        except (
            MySQLCreateApplicationDatabaseAndScopedUserError,
            MySQLGetMySQLVersionError,
            MySQLGrantPrivilegesToUserError,
        ) as e:
            logger.exception("Failed to set up database relation", exc_info=e)
            self.charm.unit.status = BlockedStatus("Failed to create scoped user")
        except TimeoutError:
            logger.exception("Timed out waiting for k8s service to be ready")
            raise
        except KubernetesClientError:
            logger.exception("Failed to create k8s services for endpoints")
            self.charm.unit.status = BlockedStatus(
                "Permission to create k8s services denied. `juju trust`"
            )
            event.defer()

    def _on_mysql_pebble_ready(self, _: PebbleReadyEvent) -> None:
        """Handle the mysql pebble ready event.

        Update a value in the peer app databag to trigger the peer_relation_changed
        handler which will in turn update the endpoints.
        """
        container = self.charm.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            return

        relations = self.charm.model.relations.get(DB_RELATION_NAME)
        if not self.charm.cluster_initialized and not relations:
            return

        if not isinstance(self.charm.unit.status, ActiveStatus):
            return

        if not self.charm._mysql.is_instance_in_cluster(self.charm.unit_label):
            logger.debug(f"Unit {self.charm.unit.name} is not yet a member of the cluster")
            return

        container_restarts = int(self.charm.unit_peer_data.get(CONTAINER_RESTARTS, "0"))
        self.charm.unit_peer_data[CONTAINER_RESTARTS] = str(container_restarts + 1)

        try:
            self._configure_endpoints(None)
        except Exception:
            # catch all exception to avoid uncommitted databag keys
            # from other pebble-ready handlers succeed
            # see: https://github.com/canonical/mysql-k8s-operator/issues/457
            logger.exception("Failed to update endpoints on database provider pebble ready event")

    def _configure_endpoints(self, _) -> None:
        """Update the endpoints + read_only_endpoints."""
        container = self.charm.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            return

        relations = self.charm.model.relations.get(DB_RELATION_NAME, [])
        if not relations or not self.charm.unit_initialized():
            return

        relation_data = self.database.fetch_relation_data()
        for relation in relations:
            # only update endpoints if on_database_requested on any
            # relation
            if relation.id in relation_data:
                break
            return

        self.charm._mysql.update_endpoints(DB_RELATION_NAME)

    def _on_update_status(self, _) -> None:
        """Handle the update status event.

        Primarily used to update the endpoints + read_only_endpoints.
        """
        if self.charm._is_cluster_blocked():
            return

        if self.charm.upgrade.state == "failed":
            # skip updating endpoints if upgrade failed
            # unit pod still will be labeled from another unit
            logger.debug("Skip labelling pods on failed upgrade")
            return

        container = self.charm.unit.get_container(CONTAINER_NAME)
        if (
            not container.can_connect()
            or not self.charm.cluster_initialized
            or not self.charm.unit_initialized()
        ):
            return

        self.charm._mysql.update_endpoints(DB_RELATION_NAME)

    def _on_database_broken(self, event: RelationBrokenEvent) -> None:
        """Handle the removal of database relation.

        Remove users, keeping database intact.

        Includes users created by MySQL Router for MySQL Router <-> application relation
        """
        if not self.charm.unit.is_leader():
            # run once by the leader
            return

        if self.charm.removing_unit:
            # safeguard against relation broken being triggered for
            # a unit being torn down (instead of un-related). See:
            # https://bugs.launchpad.net/juju/+bug/1979811
            return

        if len(self.model.relations[DB_RELATION_NAME]) == 1:
            # remove kubernetes service when last relation is removed
            self.charm.k8s_helpers.delete_endpoint_services(["primary", "replicas"])

        relation_id = event.relation.id
        try:
            if self.charm._mysql.does_mysql_user_exist(self._get_username(relation_id), "%"):
                self.charm._mysql.delete_users_for_relation(self._get_username(relation_id))
            elif self.charm._mysql.does_mysql_user_exist(
                self._get_username(relation_id, legacy=True), "%"
            ):
                self.charm._mysql.delete_users_for_relation(
                    self._get_username(relation_id, legacy=True)
                )
            else:
                logger.warning(f"User(s) not found for relation {relation_id}")
                return
            logger.info(f"Removed user(s) for relation {relation_id}")
        except MySQLDeleteUsersForRelationError:
            logger.error(f"Failed to delete user(s) for relation {relation_id}")

    def _on_database_provides_relation_departed(self, event: RelationDepartedEvent) -> None:
        """Remove MySQL Router cluster metadata & router user for departing unit."""
        if not self.charm.unit.is_leader():
            return
        if event.departing_unit.app.name == self.charm.app.name:
            return

        users = self.charm._mysql.get_mysql_router_users_for_unit(
            relation_id=event.relation.id, mysql_router_unit_name=event.departing_unit.name
        )
        if not users:
            return

        if len(users) > 1:
            logger.error(
                f"More than one router user for departing unit {event.departing_unit.name}"
            )
            return

        user = users[0]
        try:
            self.charm._mysql.delete_user(user.username)
            logger.info(f"Deleted router user {user.username}")
        except MySQLDeleteUserError:
            logger.error(f"Failed to delete user {user.username}")
        try:
            self.charm._mysql.remove_router_from_cluster_metadata(user.router_id)
            logger.info(f"Removed router from metadata {user.router_id}")
        except MySQLRemoveRouterFromMetadataError:
            logger.error(f"Failed to remove router from metadata with ID {user.router_id}")
