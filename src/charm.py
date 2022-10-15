#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for MySQL."""

import logging
from typing import Dict, Optional

from charms.mysql.v0.mysql import (
    MySQLAddInstanceToClusterError,
    MySQLConfigureInstanceError,
    MySQLConfigureMySQLUsersError,
    MySQLCreateClusterError,
    MySQLGetMySQLVersionError,
)
from charms.rolling_ops.v0.rollingops import RollingOpsManager
from ops.charm import (
    ActionEvent,
    CharmBase,
    LeaderElectedEvent,
    RelationChangedEvent,
    RelationDepartedEvent,
    RelationJoinedEvent,
)
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import Layer
from tenacity import RetryError, Retrying, stop_after_attempt, wait_fixed

from constants import (
    CLUSTER_ADMIN_PASSWORD_KEY,
    CLUSTER_ADMIN_USERNAME,
    CONFIGURED_FILE,
    MYSQLD_SERVICE,
    PASSWORD_LENGTH,
    PEER,
    REQUIRED_USERNAMES,
    ROOT_PASSWORD_KEY,
    ROOT_USERNAME,
    SERVER_CONFIG_PASSWORD_KEY,
    SERVER_CONFIG_USERNAME,
)
from mysqlsh_helpers import (
    MySQL,
    MySQLCreateCustomConfigFileError,
    MySQLInitialiseMySQLDError,
    MySQLRemoveInstancesNotOnlineError,
    MySQLRemoveInstancesNotOnlineRetryError,
)
from relations.database import DatabaseRelation
from relations.mysql import MySQLRelation
from relations.mysql_tls import MySQLTLS
from relations.osm_mysql import MySQLOSMRelation
from utils import generate_random_hash, generate_random_password

logger = logging.getLogger(__name__)


class MySQLOperatorCharm(CharmBase):
    """Operator framework charm for MySQL."""

    def __init__(self, *args):
        super().__init__(*args)

        # Lifecycle events
        self.framework.observe(self.on.mysql_pebble_ready, self._on_mysql_pebble_ready)
        self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

        self.framework.observe(self.on[PEER].relation_joined, self._on_peer_relation_joined)
        self.framework.observe(self.on[PEER].relation_changed, self._on_peer_relation_changed)
        self.framework.observe(self.on[PEER].relation_departed, self._on_peer_relation_departed)

        # Actions events
        self.framework.observe(self.on.get_cluster_status_action, self._get_cluster_status)
        self.framework.observe(self.on.get_password_action, self._on_get_password)
        self.framework.observe(self.on.set_password_action, self._on_set_password)

        self.mysql_relation = MySQLRelation(self)
        self.database_relation = DatabaseRelation(self)
        self.osm_mysql_relation = MySQLOSMRelation(self)
        self.tls = MySQLTLS(self)
        self.restart_manager = RollingOpsManager(
            charm=self, relation="restart", callback=self._restart
        )

    @property
    def peers(self):
        """Retrieve the peer relation (`ops.model.Relation`)."""
        return self.model.get_relation(PEER)

    @property
    def app_peer_data(self) -> Dict:
        """Application peer relation data object."""
        if self.peers is None:
            return {}

        return self.peers.data[self.app]

    @property
    def unit_peer_data(self) -> Dict:
        """Unit peer relation data object."""
        if self.peers is None:
            return {}

        return self.peers.data[self.unit]

    @property
    def _mysql(self):
        """Returns an instance of the MySQL object from mysqlsh_helpers."""
        peer_data = self.peers.data[self.app]

        return MySQL(
            self.get_unit_hostname(self.unit.name),
            peer_data["cluster-name"],
            self.get_secret("app", ROOT_PASSWORD_KEY),
            SERVER_CONFIG_USERNAME,
            self.get_secret("app", SERVER_CONFIG_PASSWORD_KEY),
            CLUSTER_ADMIN_USERNAME,
            self.get_secret("app", CLUSTER_ADMIN_PASSWORD_KEY),
            self.unit.get_container("mysql"),
        )

    @property
    def _is_peer_data_set(self):
        peer_data = self.peers.data[self.app]

        return (
            peer_data.get("cluster-name")
            and self.get_secret("app", ROOT_PASSWORD_KEY)
            and self.get_secret("app", SERVER_CONFIG_PASSWORD_KEY)
            and self.get_secret("app", CLUSTER_ADMIN_PASSWORD_KEY)
            and peer_data.get("allowlist")
        )

    @property
    def cluster_initialized(self):
        """Returns True if the cluster is initialized."""
        return self.peers.data[self.app].get("units-added-to-cluster", "0") >= "1"

    @property
    def _pebble_layer(self) -> Layer:
        """Return a layer for the pebble service."""
        return Layer(
            {
                "summary": "mysqld layer",
                "description": "pebble config layer for mysqld",
                "services": {
                    MYSQLD_SERVICE: {
                        "override": "replace",
                        "summary": "mysqld",
                        "command": "mysqld",
                        "startup": "enabled",
                        "user": "mysql",
                        "group": "mysql",
                    }
                },
            }
        )

    def get_unit_hostname(self, unit_name: str) -> str:
        """Get the hostname.localdomain for a unit.

        Translate juju unit name to hostname.localdomain, necessary
        for correct name resolution under k8s.

        Args:
            unit_name: unit name
        Returns:
            A string representing the hostname.localdomain of the unit.
        """
        return f"{unit_name.replace('/', '-')}.{self.app.name}-endpoints"

    def _get_unit_fqdn(self, unit_name: str) -> str:
        """Create a fqdn for a unit.

        Translate juju unit name to resolvable hostname.

        Args:
            unit_name: unit name
        Returns:
            A string representing the fqdn of the unit.
        """
        return f"{self.get_unit_hostname(unit_name)}.{self.model.name}.svc.cluster.local"

    def get_secret(self, scope: str, key: str) -> Optional[str]:
        """Get secret from the secret storage."""
        if scope == "unit":
            return self.unit_peer_data.get(key, None)
        elif scope == "app":
            return self.app_peer_data.get(key, None)
        else:
            raise RuntimeError("Unknown secret scope.")

    def set_secret(self, scope: str, key: str, value: Optional[str]) -> None:
        """Set secret in the secret storage."""
        if scope == "unit":
            if not value:
                del self.unit_peer_data[key]
                return
            self.unit_peer_data.update({key: value})
        elif scope == "app":
            if not value:
                del self.app_peer_data[key]
                return
            self.app_peer_data.update({key: value})
        else:
            raise RuntimeError("Unknown secret scope.")

    # =========================================================================
    # Charm event handlers
    # =========================================================================

    def _on_config_changed(self, _) -> None:
        """Handle the config changed event."""
        # Only execute on unit leader
        if not self.unit.is_leader():
            return

        # Set the cluster name in the peer relation databag if it is not already set
        peer_data = self.peers.data[self.app]

        if not peer_data.get("cluster-name"):
            peer_data["cluster-name"] = (
                self.config.get("cluster-name") or f"cluster_{generate_random_hash()}"
            )

        # initialise allowlist with leader hostname
        if not peer_data.get("allowlist"):
            peer_data["allowlist"] = f"{self._get_unit_fqdn(self.unit.name)}"

    def _on_leader_elected(self, event: LeaderElectedEvent) -> None:
        """Handle the leader elected event.

        Set config values in the peer relation databag if not already set.
        Idempotently remove unreachable instances from the cluster and update
        the allowlist accordingly.
        """
        # Set required passwords if not already set
        required_passwords = [
            ROOT_PASSWORD_KEY,
            SERVER_CONFIG_PASSWORD_KEY,
            CLUSTER_ADMIN_PASSWORD_KEY,
        ]

        for required_password in required_passwords:
            if not self.get_secret("app", required_password):
                logger.debug(f"Setting {required_password}")
                self.set_secret(
                    "app", required_password, generate_random_password(PASSWORD_LENGTH)
                )

        # If this node was elected a leader due to a prior leader unit being down scaled
        if self._is_peer_data_set and self.cluster_initialized:
            self.unit.status = MaintenanceStatus("Removing unreachable instances")

            # Remove unreachable instances from the cluster
            try:
                self._mysql.remove_instances_not_online()
            except (MySQLRemoveInstancesNotOnlineError, MySQLRemoveInstancesNotOnlineRetryError):
                logger.debug("Unable to remove unreachable instances from the cluster")
                self.unit.status = BlockedStatus("Failed to remove unreachable instances")

            self.unit.status = ActiveStatus()

    def _on_mysql_pebble_ready(self, event):
        """Pebble ready handler.

        Define and start a pebble service and bootstrap instance.
        """
        if not self._is_peer_data_set:
            self.unit.status = WaitingStatus("Waiting for leader election.")
            logger.debug("Leader not ready yet, waiting...")
            event.defer()
            return

        container = event.workload

        if container.exists(CONFIGURED_FILE):
            # When reusing a volume
            # Configure the layer when changed
            current_layer = container.get_plan()
            new_layer = self._pebble_layer

            if new_layer.services != current_layer:
                logger.info("Add pebble layer")
                container.add_layer(MYSQLD_SERVICE, new_layer, combine=True)
                container.restart(MYSQLD_SERVICE)
                self._mysql.wait_until_mysql_connection()
            self.unit.status = ActiveStatus()
            return

        # First run setup
        self.unit.status = MaintenanceStatus("Initialising mysqld")
        try:

            # Run mysqld for the first time to
            # bootstrap the data directory and users
            logger.debug("Initialising instance")
            self._mysql.initialise_mysqld()

            # Create custom server config file
            logger.debug("Create custom config")
            self._mysql.create_custom_config_file(
                report_host=self.get_unit_hostname(self.unit.name)
            )

            # Add the pebble layer
            container.add_layer(MYSQLD_SERVICE, self._pebble_layer, combine=False)
            container.restart(MYSQLD_SERVICE)
            logger.debug("Waiting for instance to be ready")
            self._mysql.wait_until_mysql_connection()
            logger.info("Configuring instance")
            # Configure all base users and revoke
            # privileges from the root users
            self._mysql.configure_mysql_users()
            # Configure instance as a cluster node
            self._mysql.configure_instance()
            # set workload version
            workload_version = self._mysql.get_mysql_version()
            self.unit.set_workload_version(workload_version)

        except (
            MySQLConfigureInstanceError,
            MySQLConfigureMySQLUsersError,
            MySQLInitialiseMySQLDError,
            MySQLCreateCustomConfigFileError,
        ) as e:
            self.unit.status = BlockedStatus("Unable to configure instance")
            logger.debug("Unable to configure instance: {}".format(e))
            return
        except MySQLGetMySQLVersionError:
            # Do not block the charm if the version cannot be retrieved
            pass

        if self.unit.is_leader():
            try:
                # Create the cluster when is the leader unit
                unit_label = self.unit.name.replace("/", "-")
                self._mysql.create_cluster(unit_label)
                logger.debug("Cluster configured on unit")
                # Create control file in data directory
                container.push(CONFIGURED_FILE, make_dirs=True, source="configured")
                self.peers.data[self.app]["units-added-to-cluster"] = "1"
                self.unit.status = ActiveStatus()
            except MySQLCreateClusterError as e:
                self.unit.status = BlockedStatus("Unable to create cluster")
                logger.debug("Unable to create cluster: {}".format(e))
        else:
            # When unit is not the leader, it should wait
            # for the leader to configure it a cluster node
            self.unit.status = WaitingStatus("Waiting for instance to join the cluster")
            # Create control file in data directory
            container.push(CONFIGURED_FILE, make_dirs=True, source="configured")

    def _on_peer_relation_joined(self, event: RelationJoinedEvent):
        """Handle the peer relation joined event."""
        # Only leader unit add instances to the cluster
        if not self.unit.is_leader():
            return

        # Defer run when leader is not active
        if not isinstance(self.unit.status, ActiveStatus):
            event.defer()
            return

        new_instance_fqdn = self._get_unit_fqdn(event.unit.name)
        new_instance_label = event.unit.name.replace("/", "-")

        # Check if new instance is ready to be added to the cluster
        if not self._mysql.is_instance_configured_for_innodb(
            new_instance_fqdn, new_instance_label
        ):
            event.defer()
            return

        # Check if instance was already added to the cluster
        if self._mysql.is_instance_in_cluster(new_instance_label):
            logger.debug(f"Instance {new_instance_fqdn} already in cluster")
            return

        # Add new instance to the cluster
        try:
            cluster_primary = self._mysql.get_cluster_primary_address()
            if not cluster_primary:
                self.unit.status = BlockedStatus("Unable to retrieve the cluster primary")
                return

            self._mysql.add_instance_to_cluster(
                new_instance_fqdn, new_instance_label, from_instance=cluster_primary
            )
            logger.debug(f"Added instance {new_instance_fqdn} to cluster")

            # Update 'units-added-to-cluster' counter in the peer relation databag
            # in order to trigger a relation_changed event which will move the added unit
            # into ActiveStatus
            units_started = int(self.peers.data[self.app]["units-added-to-cluster"])
            self.peers.data[self.app]["units-added-to-cluster"] = str(units_started + 1)

        except MySQLAddInstanceToClusterError:
            logger.debug(f"Unable to add instance {new_instance_fqdn} to cluster.")
            self.unit.status = BlockedStatus("Unable to add instance to cluster")

    def _on_peer_relation_changed(self, event: RelationChangedEvent) -> None:
        """Handle the relation changed event."""
        # This handler is only taking care of setting
        # active status for secondary units
        if not self._is_peer_data_set:
            # Avoid running too early
            event.defer()
            return

        instance_label = self.unit.name.replace("/", "-")
        # Test if non-leader unit is ready
        if isinstance(self.unit.status, WaitingStatus) and self._mysql.is_instance_in_cluster(
            instance_label
        ):
            self.unit.status = ActiveStatus()
            logger.debug(f"Instance {instance_label} is cluster member")

    def _on_peer_relation_departed(self, event: RelationDepartedEvent) -> None:
        """Handle the relation departed event.

        Update the allowlist to remove the departing unit from the leader unit.
        Only on the leader, update the allowlist in the peer relation databag
        and remove unreachable instances from the cluster.
        """
        if not self.unit.is_leader():
            return

        self.unit.status = MaintenanceStatus("Removing unreachable instances")

        try:
            self._mysql.remove_instances_not_online()
        except (MySQLRemoveInstancesNotOnlineError, MySQLRemoveInstancesNotOnlineRetryError):
            logger.debug("Unable to remove unreachable instances from the cluster")
            self.unit.status = BlockedStatus("Failed to remove unreachable instances")

        self.unit.status = ActiveStatus()

    # =========================================================================
    # Charm action handlers
    # =========================================================================
    def _on_get_password(self, event: ActionEvent) -> None:
        """Action used to retrieve the system user's password."""
        username = event.params.get("username") or ROOT_USERNAME

        if username not in REQUIRED_USERNAMES:
            raise RuntimeError("Invalid username.")

        if username == ROOT_USERNAME:
            secret_key = ROOT_PASSWORD_KEY
        elif username == SERVER_CONFIG_USERNAME:
            secret_key = SERVER_CONFIG_PASSWORD_KEY
        elif username == CLUSTER_ADMIN_USERNAME:
            secret_key = CLUSTER_ADMIN_PASSWORD_KEY
        else:
            raise RuntimeError("Invalid username.")

        event.set_results({"username": username, "password": self.get_secret("app", secret_key)})

    def _on_set_password(self, event: ActionEvent) -> None:
        """Action used to update/rotate the system user's password."""
        if not self.unit.is_leader():
            raise RuntimeError("set-password action can only be run on the leader unit.")

        username = event.params.get("username") or ROOT_USERNAME

        if username not in REQUIRED_USERNAMES:
            raise RuntimeError("Invalid username.")

        if username == ROOT_USERNAME:
            secret_key = ROOT_PASSWORD_KEY
        elif username == SERVER_CONFIG_USERNAME:
            secret_key = SERVER_CONFIG_PASSWORD_KEY
        elif username == CLUSTER_ADMIN_USERNAME:
            secret_key = CLUSTER_ADMIN_PASSWORD_KEY
        else:
            raise RuntimeError("Invalid username.")

        new_password = event.params.get("password") or generate_random_password(PASSWORD_LENGTH)

        self._mysql.update_user_password(username, new_password)

        self.set_secret("app", secret_key, new_password)

    def _get_cluster_status(self, event: ActionEvent) -> None:
        """Get the cluster status without topology."""
        event.set_results(self._mysql.get_cluster_status())

    def _restart(self, _) -> None:
        """Restart server rolling ops callback function.

        Hold execution until server is back in the cluster.
        Used exclusively for rolling restarts.
        """
        logger.debug("Restarting mysqld daemon")

        container = self.unit.get_container("mysql")
        container.restart(MYSQLD_SERVICE)

        unit_label = self.unit.name.replace("/", "-")

        try:
            for attempt in Retrying(stop=stop_after_attempt(24), wait=wait_fixed(5)):
                with attempt:
                    if self._mysql.is_instance_in_cluster(unit_label):
                        # TODO: update status setting to set message with
                        # `self.active_status_message` once it gets merged
                        self.unit.status = ActiveStatus()
                        return
                    raise Exception
        except RetryError:
            logger.error("Unable to rejoin mysqld instance to the cluster.")
            self.unit.status = BlockedStatus("Restarted node unable to rejoin the cluster")


if __name__ == "__main__":
    main(MySQLOperatorCharm)
