# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of the standard relation."""

import json
import logging
import time

from charms.data_platform_libs.v0.database_provides import (
    DatabaseProvides,
    DatabaseRequestedEvent,
)
from charms.mysql.v0.mysql import (
    MySQLClientError,
    MySQLCreateApplicationDatabaseAndScopedUserError,
    MySQLDeleteUserForRelationError,
    MySQLGetMySQLVersionError,
    MySQLGrantPrivilegesToUserError,
    MySQLUpgradeUserForMySQLRouterError,
)
from ops.charm import (
    PebbleReadyEvent,
    RelationBrokenEvent,
    RelationDepartedEvent,
    RelationJoinedEvent,
)
from ops.framework import Object
from ops.model import BlockedStatus

from constants import (
    CONTAINER_NAME,
    CONTAINER_RESTARTS,
    DB_RELATION_NAME,
    PASSWORD_LENGTH,
    PEER,
    UNIT_ENDPOINTS_KEY,
)
from utils import generate_random_password

logger = logging.getLogger(__name__)


class MySQLProvider(Object):
    """Standard database relation class."""

    def __init__(self, charm):
        super().__init__(charm, DB_RELATION_NAME)

        self.charm = charm

        self.database = DatabaseProvides(self.charm, relation_name=DB_RELATION_NAME)
        self.framework.observe(self.database.on.database_requested, self._on_database_requested)

        self.framework.observe(
            self.charm.on[DB_RELATION_NAME].relation_broken, self._on_database_broken
        )

        self.framework.observe(
            self.charm.on[PEER].relation_departed, self._on_peer_relation_departed
        )
        self.framework.observe(self.charm.on[PEER].relation_joined, self._on_peer_relation_joined)
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
        if password := relation.data[self.charm.app].get("password"):
            return password
        password = generate_random_password(PASSWORD_LENGTH)
        relation.data[self.charm.app]["password"] = password
        return password

    def _update_endpoints_from_unit_peer_data(self, relation_id: int) -> None:
        """Updates the endpoints + read-only-endpoints in the relation from unit peer databag.

        Args:
            relation_id: The id of the relation for which to update the endpoints
        """
        logger.debug("Updating endpoints from unit peer data")

        primary_endpoint, read_only_endpoints, latest_timestamp = None, None, -1

        mysql_units = self.charm.model.relations[PEER][0].units
        mysql_units.add(self.charm.unit)

        # get the primary endpoint and read_only_endpoints from the latest timestamped
        # unit peer databag
        for unit in mysql_units:
            unit_endpoints = self.charm.peers.data[unit].get(UNIT_ENDPOINTS_KEY)

            if not unit_endpoints or unit_endpoints == "error":
                continue

            unit_endpoints = json.loads(unit_endpoints)

            if unit_endpoints["timestamp"] > latest_timestamp:
                primary_endpoint = unit_endpoints["endpoint"]
                read_only_endpoints = unit_endpoints["read-only-endpoints"]
                latest_timestamp = unit_endpoints["timestamp"]

        # no-op if no endpoints exist in unit peer databag
        if not primary_endpoint or not read_only_endpoints:
            return

        self.database.set_endpoints(relation_id, primary_endpoint)
        self.database.set_read_only_endpoints(relation_id, read_only_endpoints)

    def _update_endpoints(self, relation_id: int) -> None:
        """Updates the endpoints + read-only-endpoints in the relation.

        Args:
            relation_id: The id of the relation for which to update the endpoints
        """
        try:
            # update endpoints from unit peer databag if mysqld stopped on this unit
            if self.charm._mysql.check_if_mysqld_process_stopped():
                self._update_endpoints_from_unit_peer_data(relation_id)
                return

            cluster_status = self.charm._mysql.get_cluster_status()
            if not cluster_status:
                self._update_endpoints_from_unit_peer_data(relation_id)
                return

            logger.debug(f"Updating the endpoints for relation {relation_id}")
            primary_endpoints = [
                member["address"]
                for member in cluster_status["defaultreplicaset"]["topology"].values()
                if member["mode"] == "r/w" and member["status"] == "online"
            ]
            if not primary_endpoints:
                self._update_endpoints_from_unit_peer_data(relation_id)
                return

            self.database.set_endpoints(relation_id, primary_endpoints[0])

            logger.debug(f"Updating the read_only_endpoints for relation {relation_id}")
            read_only_endpoints = ",".join(
                [
                    member["address"]
                    for member in cluster_status["defaultreplicaset"]["topology"].values()
                    if member["status"] == "online"
                ]
            )
            self.database.set_read_only_endpoints(relation_id, read_only_endpoints)
        except MySQLClientError as e:
            logger.exception("Failed to get primary", exc_info=e)
            self._update_endpoints_from_unit_peer_data(relation_id)

    # =============
    # Handlers
    # =============

    def _on_database_requested(self, event: DatabaseRequestedEvent) -> None:
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
        extra_user_roles = []
        if event.extra_user_roles:
            extra_user_roles = event.extra_user_roles.split(",")
        # user name is derived from the relation id
        db_user = f"relation-{relation_id}"
        db_pass = self._get_or_set_password(event.relation)

        remote_app = event.app.name

        try:
            cluster_status = self.charm._mysql.get_cluster_status()
            if not cluster_status:
                self.unit.status = BlockedStatus("Failed to get cluster status")
                return

            primary_endpoints = [
                member["address"]
                for member in cluster_status["defaultreplicaset"]["topology"].values()
                if member["mode"] == "r/w" and member["status"] == "online"
            ]
            if not primary_endpoints:
                logger.exception("Unable to retrieve primary endpoint address")
                self.unit.status = BlockedStatus("Failed to get primary endpoint")
                return

            db_version = self.charm._mysql.get_mysql_version()
            self.database.set_credentials(relation_id, db_user, db_pass)
            self.database.set_version(relation_id, db_version)

            self.database.set_endpoints(relation_id, primary_endpoints[0])

            read_only_endpoints = ",".join(
                [
                    member["address"]
                    for member in cluster_status["defaultreplicaset"]["topology"].values()
                    if member["status"] == "online"
                ]
            )

            self.database.set_read_only_endpoints(relation_id, read_only_endpoints)
            # TODO:
            # add setup of tls, tls_ca and status
            # add extra roles parsing from relation data
            self.charm._mysql.create_application_database_and_scoped_user(
                db_name, db_user, db_pass, "%", remote_app
            )

            if "mysqlrouter" in extra_user_roles:
                self.charm._mysql.upgrade_user_for_mysqlrouter(db_user, "%")
                self.charm._mysql.grant_privileges_to_user(
                    db_user, "%", ["CREATE USER"], with_grant_option=True
                )

            logger.info(f"Created user for app {remote_app}")
        except (
            MySQLCreateApplicationDatabaseAndScopedUserError,
            MySQLGetMySQLVersionError,
            MySQLClientError,
            MySQLUpgradeUserForMySQLRouterError,
            MySQLGrantPrivilegesToUserError,
        ) as e:
            logger.exception("Failed to set up database relation", exc_info=e)
            self.charm.unit.status = BlockedStatus("Failed to create scoped user")

    def _on_mysql_pebble_ready(self, event: PebbleReadyEvent) -> None:
        """Handle the mysql pebble ready event.

        Update a value in the peer app databag to trigger the peer_relation_changed
        handler which will in turn update the endpoints.
        """
        container = self.charm.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            event.defer()
            return

        if not self.charm.cluster_initialized:
            return

        charm_unit_label = self.charm.unit.name.replace("/", "-")
        if not self.charm._mysql.is_instance_in_cluster(charm_unit_label):
            logger.debug(f"Unit {self.charm.unit.name} is not yet a member of the cluster")
            event.defer()
            return

        container_restarts = int(self.charm.unit_peer_data.get(CONTAINER_RESTARTS, "0"))
        self.charm.unit_peer_data[CONTAINER_RESTARTS] = str(container_restarts + 1)

        self._configure_endpoints(None)

    def _on_peer_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Handle the peer relation joined event.

        Update the endpoints + read_only_endpoints.
        """
        relations = self.charm.model.relations.get(DB_RELATION_NAME, [])
        if not self.charm.unit.is_leader() or not relations or not self.charm.cluster_initialized:
            return

        event_unit_label = event.unit.name.replace("/", "-")
        if not self.charm._mysql.is_instance_in_cluster(event_unit_label):
            logger.debug(f"Unit {event.unit.name} is not yet a member of the cluster")
            event.defer()
            return

        relation_data = self.database.fetch_relation_data()
        for relation in relations:
            # only update endpoints if on_database_requested has executed
            if relation.id not in relation_data:
                continue

            self._update_endpoints(relation.id)

    def _on_peer_relation_departed(self, event: RelationDepartedEvent) -> None:
        """Handle the peer relation departed event.

        Update the endpoints + read_only_endpoints.
        """
        relations = self.charm.model.relations.get(DB_RELATION_NAME, [])
        if not self.charm.unit.is_leader() or not relations or not self.charm.cluster_initialized:
            return

        departing_unit_name = event.departing_unit.name.replace("/", "-")

        if self.charm._mysql.is_instance_in_cluster(departing_unit_name):
            logger.debug(f"Departing unit {departing_unit_name} still in cluster")
            event.defer()
            return

        relation_data = self.database.fetch_relation_data()
        for relation in relations:
            # only update endpoints if on_database_requested has executed
            if relation.id not in relation_data:
                continue

            self._update_endpoints(relation.id)

    def _configure_endpoints(self, _) -> None:
        """Update the endpoints + read_only_endpoints."""
        relations = self.charm.model.relations.get(DB_RELATION_NAME, [])
        if not self.charm.unit.is_leader() or not relations or not self.charm.cluster_initialized:
            return

        relation_data = self.database.fetch_relation_data()
        for relation in relations:
            # only update endpoints if on_database_requested has executed
            if relation.id not in relation_data:
                continue

            self._update_endpoints(relation.id)

    def _on_update_status(self, _) -> None:
        """Handle the update status event.

        Primarily used to update the endpoints + read_only_endpoints.
        """
        container = self.charm.unit.get_container(CONTAINER_NAME)
        if (
            not container.can_connect()
            or not self.charm.cluster_initialized
            or not self.charm.unit_initialized
        ):
            return

        if self.charm.unit.is_leader():
            # pass in None as the event as it is not being utilized in _configure_endpoints
            self._configure_endpoints(None)

        # do not set endpoints in unit peer databag if mysqld stopped on this unit
        # (as mysqlsh commands will hang instead of failing due to the stopped process)
        if self.charm._mysql.check_if_mysqld_process_stopped():
            return

        cluster_status = self.charm._mysql.get_cluster_status()
        if not cluster_status:
            return

        primary_endpoints = [
            member["address"]
            for member in cluster_status["defaultreplicaset"]["topology"].values()
            if member["mode"] == "r/w" and member["status"] == "online"
        ]
        if not primary_endpoints:
            return

        read_only_endpoints = ",".join(
            [
                member["address"]
                for member in cluster_status["defaultreplicaset"]["topology"].values()
                if member["status"] == "online"
            ]
        )

        unit_endpoints = json.loads(self.charm.unit_peer_data.get(UNIT_ENDPOINTS_KEY, "{}"))

        if (
            unit_endpoints.get("endpoint") != primary_endpoints[0]
            or unit_endpoints.get("read-only-endpoints") != read_only_endpoints
        ):
            self.charm.unit_peer_data[UNIT_ENDPOINTS_KEY] = json.dumps(
                {
                    "endpoint": primary_endpoints[0],
                    "read-only-endpoints": read_only_endpoints,
                    "timestamp": int(time.time()),
                }
            )

    def _on_database_broken(self, event: RelationBrokenEvent) -> None:
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
