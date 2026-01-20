# Copyright 2022 Canonical Ltd.
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

"""MySQL helper class and functions.

The `mysql` module provides an abstraction class and methods for for managing a
Group Replication enabled MySQL cluster.

The `MySQLBase` abstract class must be inherited and have its abstract methods
implemented for each platform (vm/k8s) before being directly used in charm code.

An example of inheriting `MySQLBase` and implementing the abstract methods plus extending it:

```python
from charms.mysql.v0.mysql import MySQLBase
from tenacity import retry, stop_after_delay, wait_fixed

class MySQL(MySQLBase):
    def __init__(
        self,
        instance_address: str,
        cluster_name: str,
        root_password: str,
        server_config_user: str,
        server_config_password: str,
        cluster_admin_user: str,
        cluster_admin_password: str,
        new_parameter: str
    ):
        super().__init__(
                instance_address=instance_address,
                cluster_name=cluster_name,
                root_password=root_password,
                server_config_user=server_config_user,
                server_config_password=server_config_password,
                cluster_admin_user=cluster_admin_user,
                cluster_admin_password=cluster_admin_password,
            )
        # Add new attribute
        self.new_parameter = new_parameter
    ...
```

The module also provides a set of custom exceptions, used to trigger specific
error handling on the subclass and in the charm code.
"""

import configparser
import hashlib
import io
import json
import logging
import os
import re
import sys
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Generator,
    Literal,
    Type,
    get_args,
)

import ops
from charms.data_platform_libs.v0.data_interfaces import DataPeerData, DataPeerUnitData
from constants import (
    BACKUPS_PASSWORD_KEY,
    BACKUPS_USERNAME,
    CHARMED_MYSQL_PITR_HELPER,
    CLUSTER_ADMIN_PASSWORD_KEY,
    CLUSTER_ADMIN_USERNAME,
    COS_AGENT_RELATION_NAME,
    GR_MAX_MEMBERS,
    MONITORING_PASSWORD_KEY,
    MONITORING_USERNAME,
    PASSWORD_LENGTH,
    PEER,
    ROOT_PASSWORD_KEY,
    ROOT_USERNAME,
    SECRET_KEY_FALLBACKS,
    SERVER_CONFIG_PASSWORD_KEY,
    SERVER_CONFIG_USERNAME,
)
from mysql_shell.builders import (
    CharmAuthorizationQueryBuilder,
    CharmLockingQueryBuilder,
    CharmLoggingQueryBuilder,
    StringQueryQuoter,
)
from mysql_shell.clients import (
    MySQLClusterClient,
    MySQLInstanceClient,
)
from mysql_shell.executors import BaseExecutor
from mysql_shell.executors.errors import ExecutionError
from mysql_shell.models.account import User
from mysql_shell.models.cluster import ClusterGlobalStatus, ClusterRole, ClusterStatus
from mysql_shell.models.connection import ConnectionDetails
from mysql_shell.models.instance import InstanceRole, InstanceState
from mysql_shell.models.statement import LogType
from mysql_shell.models.statement import VariableScope as Scope
from ops.charm import ActionEvent, CharmBase, RelationBrokenEvent
from ops.model import Unit
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
    wait_random,
)
from utils import generate_random_password

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from charms.mysql.v0.async_replication import MySQLAsyncReplicationOffer

# The unique Charmhub library identifier, never change it
LIBID = "8c1428f06b1b4ec8bf98b7d980a38a8c"

# Increment this major API version when introducing breaking changes
LIBAPI = 0
LIBPATCH = 100

PYDEPS = ["mysql_shell_client ~= 0.6"]

UNIT_TEARDOWN_LOCKNAME = "unit-teardown"
UNIT_ADD_LOCKNAME = "unit-add"

BYTES_1GiB = 1073741824  # 1 gibibyte
BYTES_1GB = 1000000000  # 1 gigabyte
BYTES_1MB = 1000000  # 1 megabyte
BYTES_1MiB = 1048576  # 1 mebibyte
RECOVERY_CHECK_TIME = 10  # seconds
GET_MEMBER_ROLE_TIME = 10  # seconds
GET_MEMBER_STATE_TIME = 10  # seconds
MAX_CONNECTIONS_FLOOR = 10
MIM_MEM_BUFFERS = 200 * BYTES_1MiB
ADMIN_PORT = 33062

# Labels are not confidential
SECRET_INTERNAL_LABEL = "secret-id"  # noqa: S105
SECRET_DELETED_LABEL = "None"  # noqa: S105

ROLE_DBA = "charmed_dba"
ROLE_DDL = "charmed_ddl"
ROLE_DML = "charmed_dml"
ROLE_READ = "charmed_read"
ROLE_STATS = "charmed_stats"
ROLE_BACKUP = "charmed_backup"
ROLE_MAX_LENGTH = 32

# TODO:
#   Remove legacy role when migrating to MySQL 8.4
#   (when breaking changes are allowed)
LEGACY_ROLE_ROUTER = "mysqlrouter"
MODERN_ROLE_ROUTER = "charmed_router"

FORBIDDEN_EXTRA_ROLES = {
    ROLE_BACKUP,
}

ALLOWED_PLUGINS = {
    "audit_log": "audit_log.so",
    "audit_log_filter": "audit_log_filter.so",
    "binlog_utils_udf": "binlog_utils_udf.so",
}

APP_SCOPE = "app"
UNIT_SCOPE = "unit"
Scopes = Literal["app", "unit"]


class Error(Exception):
    """Base class for exceptions in this module."""

    def __init__(self, message: str = "") -> None:
        """Initialize the Error class.

        Args:
            message: Optional message to pass to the exception.
        """
        super().__init__(message)
        self.message = message

    def __repr__(self):
        """String representation of the Error class."""
        return f"<{type(self).__module__}.{type(self).__name__} {self.args}>"

    @property
    def name(self):
        """Return a string representation of the model plus class."""
        return f"<{type(self).__module__}.{type(self).__name__}>"


class MySQLConfigureMySQLRolesError(Error):
    """Exception raised when creating a role fails."""


class MySQLConfigureMySQLUsersError(Error):
    """Exception raised when creating a user fails."""


class MySQLCheckUserExistenceError(Error):
    """Exception raised when checking for the existence of a MySQL user."""


class MySQLConfigureRouterUserError(Error):
    """Exception raised when configuring the MySQLRouter user."""


class MySQLCreateApplicationDatabaseError(Error):
    """Exception raised when creating application database."""


class MySQLCreateApplicationScopedUserError(Error):
    """Exception raised when creating application scoped user."""


class MySQLGetRouterUsersError(Error):
    """Exception raised when there is an issue getting MySQL Router users."""


class MySQLDeleteUsersForUnitError(Error):
    """Exception raised when there is an issue deleting users for a unit."""


class MySQLDeleteUsersForRelationError(Error):
    """Exception raised when there is an issue deleting users for a relation."""


class MySQLDeleteUserError(Error):
    """Exception raised when there is an issue deleting a user."""


class MySQLRemoveRouterFromMetadataError(Error):
    """Exception raised when there is an issue removing MySQL Router from cluster metadata."""


class MySQLConfigureInstanceError(Error):
    """Exception raised when there is an issue configuring a MySQL instance."""


class MySQLCreateClusterError(Error):
    """Exception raised when there is an issue creating an InnoDB cluster."""


class MySQLCreateClusterSetError(Error):
    """Exception raised when there is an issue creating an Cluster Set."""


class MySQLAddInstanceToClusterError(Error):
    """Exception raised when there is an issue add an instance to the MySQL InnoDB cluster."""


class MySQLRejoinInstanceToClusterError(Error):
    """Exception raised when there is an issue rejoining an instance to the MySQL InnoDB cluster."""


class MySQLRemoveInstanceError(Error):
    """Exception raised when there is an issue removing an instance."""


class MySQLInitializeJujuOperationsTableError(Error):
    """Exception raised when there is an issue initializing the juju units operations table."""


class MySQLGetMySQLVersionError(Error):
    """Exception raised when there is an issue getting the MySQL version."""


class MySQLGetClusterPrimaryAddressError(Error):
    """Exception raised when there is an issue getting the primary instance."""


class MySQLSetClusterPrimaryError(Error):
    """Exception raised when there is an issue setting the primary instance."""


class MySQLUnableToGetMemberStateError(Error):
    """Exception raised when unable to get member state."""


class MySQLGetClusterEndpointsError(Error):
    """Exception raised when there is an issue getting cluster endpoints."""


class MySQLRebootFromCompleteOutageError(Error):
    """Exception raised when there is an issue rebooting from complete outage."""


class MySQLForceQuorumFromInstanceError(Error):
    """Exception raised when there is an issue forcing quorum from an instance."""


class MySQLSetInstanceOfflineModeError(Error):
    """Exception raised when there is an issue setting instance as offline."""


class MySQLSetInstanceOptionError(Error):
    """Exception raised when there is an issue setting instance option."""


class MySQLOfflineModeAndHiddenInstanceExistsError(Error):
    """Exception raised when there is an error checking if an instance is backing up.

    We check if an instance is in offline_mode and hidden from mysql-router to determine
    this.
    """


class MySQLGetAutoTuningParametersError(Error):
    """Exception raised when there is an error computing the innodb buffer pool parameters."""


class MySQLExecuteBackupCommandsError(Error):
    """Exception raised when there is an error executing the backup commands.

    The backup commands are executed in the workload container using the pebble API.
    """


class MySQLDeleteTempBackupDirectoryError(Error):
    """Exception raised when there is an error deleting the temp backup directory."""


class MySQLRetrieveBackupWithXBCloudError(Error):
    """Exception raised when there is an error retrieving a backup from S3 with xbcloud."""


class MySQLPrepareBackupForRestoreError(Error):
    """Exception raised when there is an error preparing a backup for restore."""


class MySQLEmptyDataDirectoryError(Error):
    """Exception raised when there is an error emptying the mysql data directory."""


class MySQLRestoreBackupError(Error):
    """Exception raised when there is an error restoring a backup."""


class MySQLRestorePitrError(Error):
    """Exception raised when there is an error during point-in-time-recovery restore."""


class MySQLDeleteTempRestoreDirectoryError(Error):
    """Exception raised when there is an error deleting the temp restore directory."""


class MySQLExecError(Error):
    """Exception raised when there is an error executing commands on the mysql server."""


class MySQLStopMySQLDError(Error):
    """Exception raised when there is an error stopping the MySQLD process."""


class MySQLStartMySQLDError(Error):
    """Exception raised when there is an error starting the MySQLD process."""


class MySQLServiceNotRunningError(Error):
    """Exception raised when the MySQL service is not running."""


class MySQLTLSSetupError(Error):
    """Exception raised when there is an issue setting custom TLS config."""


class MySQLKillSessionError(Error):
    """Exception raised when there is an issue killing a connection."""


class MySQLLockAcquisitionError(Error):
    """Exception raised when a lock fails to be acquired."""


class MySQLRescanClusterError(Error):
    """Exception raised when there is an issue rescanning the cluster."""


class MySQLSetVariableError(Error):
    """Exception raised when there is an issue setting a variable."""


class MySQLSecretError(Error):
    """Exception raised when there is an issue setting/getting a secret."""


class MySQLGetAvailableMemoryError(Error):
    """Exception raised when there is an issue getting the available memory."""


class MySQLCreateReplicaClusterError(Error):
    """Exception raised when there is an issue creating a replica cluster."""


class MySQLRemoveReplicaClusterError(Error):
    """Exception raised when there is an issue removing a replica cluster."""


class MySQLPromoteClusterToPrimaryError(Error):
    """Exception raised when there is an issue promoting a replica cluster to primary."""


class MySQLRejoinClusterError(Error):
    """Exception raised when there is an issue trying to rejoin a cluster to the cluster set."""


class MySQLPluginInstallError(Error):
    """Exception raised when there is an issue installing a MySQL plugin."""


class MySQLGetGroupReplicationIDError(Error):
    """Exception raised when there is an issue acquiring current current group replication id."""


class MySQLClusterMetadataExistsError(Error):
    """Exception raised when there is an issue checking if cluster metadata exists."""


class MySQLCharmBase(CharmBase, ABC):
    """Base class to encapsulate charm related functionality.

    Meant as a means to share common charm related code between the MySQL VM and
    K8s charms.
    """

    replication_offer: "MySQLAsyncReplicationOffer"

    def __init__(self, *args):
        super().__init__(*args)

        # disable support
        disable_file = Path(f"{os.environ.get('CHARM_DIR')}/disable")  # pyright: ignore [reportArgumentType]
        if disable_file.exists():
            logger.warning(
                f"\n\tDisable file `{disable_file.resolve()}` found, the charm will skip all events."
                "\n\tTo resume normal operations, please remove the file."
            )
            self.unit.status = ops.BlockedStatus("Disabled")
            sys.exit(0)

        self.peer_relation_app = DataPeerData(
            self.model,
            relation_name=PEER,
            secret_field_name=SECRET_INTERNAL_LABEL,
            deleted_label=SECRET_DELETED_LABEL,
        )
        self.peer_relation_unit = DataPeerUnitData(
            self.model,
            relation_name=PEER,
            secret_field_name=SECRET_INTERNAL_LABEL,
            deleted_label=SECRET_DELETED_LABEL,
        )

        self.framework.observe(self.on.get_cluster_status_action, self._get_cluster_status)
        self.framework.observe(self.on.get_password_action, self._on_get_password)
        self.framework.observe(self.on.set_password_action, self._on_set_password)
        self.framework.observe(self.on.promote_to_primary_action, self._on_promote_to_primary)
        self.framework.observe(self.on.recreate_cluster_action, self._recreate_cluster)
        self.framework.observe(
            self.on[PEER].relation_changed, self.check_topology_timestamp_change
        )

        # Set in some event handlers in order to avoid passing event down a chain
        # of methods
        self.current_event = None

    @property
    @abstractmethod
    def _mysql(self) -> "MySQLBase":
        """Return the MySQL instance."""
        raise NotImplementedError

    @abstractmethod
    def get_unit_hostname(self):
        """Return unit hostname."""
        raise NotImplementedError

    @abstractmethod
    def get_unit_address(self, unit: Unit, relation_name: str) -> str:
        """Return unit address."""
        # each platform has its own way to get an arbitrary unit address
        raise NotImplementedError

    @abstractmethod
    def is_unit_busy(self) -> bool:
        """Returns whether the unit is busy."""
        raise NotImplementedError

    @staticmethod
    def get_unit_label(unit: Unit) -> str:
        """Return unit label."""
        return unit.name.replace("/", "-")

    def _on_get_password(self, event: ActionEvent) -> None:
        """Action used to retrieve the system user's password."""
        username = event.params.get("username") or ROOT_USERNAME

        valid_usernames = {
            ROOT_USERNAME: ROOT_PASSWORD_KEY,
            SERVER_CONFIG_USERNAME: SERVER_CONFIG_PASSWORD_KEY,
            CLUSTER_ADMIN_USERNAME: CLUSTER_ADMIN_PASSWORD_KEY,
            MONITORING_USERNAME: MONITORING_PASSWORD_KEY,
            BACKUPS_USERNAME: BACKUPS_PASSWORD_KEY,
        }

        secret_key = valid_usernames.get(username)
        if not secret_key:
            event.fail(
                f"The action can be run only for users used by the charm: {', '.join(valid_usernames.keys())} not {username}"
            )
            return

        event.set_results({"username": username, "password": self.get_secret("app", secret_key)})

    def _on_set_password(self, event: ActionEvent) -> None:
        """Action used to update/rotate the system user's password."""
        if not self.unit.is_leader():
            event.fail("set-password action can only be run on the leader unit.")
            return

        if self.replication_offer.role.relation_side != "replication-offer":
            event.fail("Only offer side can change password when replications is enabled")
            return

        username = event.params.get("username") or ROOT_USERNAME

        valid_usernames = {
            ROOT_USERNAME: ROOT_PASSWORD_KEY,
            SERVER_CONFIG_USERNAME: SERVER_CONFIG_PASSWORD_KEY,
            CLUSTER_ADMIN_USERNAME: CLUSTER_ADMIN_PASSWORD_KEY,
            MONITORING_USERNAME: MONITORING_PASSWORD_KEY,
            BACKUPS_USERNAME: BACKUPS_PASSWORD_KEY,
        }

        secret_key = valid_usernames.get(username)
        if not secret_key:
            event.fail(
                f"The action can be run only for users used by the charm: {', '.join(valid_usernames.keys())} not {username}"
            )
            return

        new_password = event.params.get("password") or generate_random_password(PASSWORD_LENGTH)
        host = "%" if username != ROOT_USERNAME else "localhost"

        self._mysql.update_user_password(username, new_password, host=host)

        self.set_secret("app", secret_key, new_password)

        if username == MONITORING_USERNAME and self.has_cos_relation:
            self._mysql.restart_mysql_exporter()

    def _get_cluster_status(self, event: ActionEvent) -> None:
        """Action used  to retrieve the cluster status."""
        try:
            if event.params.get("cluster-set"):
                logger.debug("Getting cluster set status")
                status = self._mysql.get_cluster_set_status(extended=0)
            else:
                logger.debug("Getting cluster status")
                status = self._mysql.get_cluster_status()

            if not status:
                event.fail("Failed to read cluster status. See logs for more information.")
                return

            # TODO:
            #   Remove `.lower()` when migrating to MySQL 8.4
            #   (when breaking changes are allowed)
            status = json.dumps(status)
            status = status.lower()
            status = json.loads(status)

            event.set_results({
                "success": True,
                "status": status,
            })
        except Exception:
            logger.exception("Error while reading cluster status")
            event.fail("Error while reading cluster status. See logs for more information.")

    def _on_promote_to_primary(self, event: ActionEvent) -> None:
        """Action for setting this unit as the cluster primary."""
        if event.params.get("scope") != "unit":
            return

        if self._mysql.get_primary_label() == self.unit_label:
            event.set_results({
                "success": False,
                "message": "Unit is already primary",
            })
            return

        if event.params.get("force"):
            # Failover
            logger.info("Forcing quorum from instance")
            try:
                self._mysql.force_quorum_from_instance()
            except MySQLForceQuorumFromInstanceError:
                logger.exception("Failed to force quorum from instance")
                event.fail("Failed to force quorum from instance. See logs for more information.")
                return
        else:
            # Switchover
            logger.info("Setting unit as cluster primary")
            try:
                self._mysql.set_cluster_primary(self.get_unit_hostname())
            except MySQLSetClusterPrimaryError:
                logger.exception("Failed to set cluster primary")
                event.fail("Failed to change cluster primary. See logs for more information.")
                return

        # Use peer relation to trigger endpoint update
        # refer to mysql_provider.py
        self.unit_peer_data.update({"topology-change-timestamp": str(int(time.time()))})
        event.set_results({
            "success": True,
            "message": "Unit is already primary",
        })

    def _recreate_cluster(self, event: ActionEvent) -> None:
        """Action used to recreate the cluster, for special cases."""
        if not self.unit.is_leader():
            event.fail("recreate-cluster action can only be run on the leader unit.")
            return

        if self.app_peer_data.get("removed-from-cluster-set"):
            # remove the flag if it exists. Allow further cluster rejoin
            del self.app_peer_data["removed-from-cluster-set"]

        # reset cluster-set-name to config or previous value
        random_hash = self.generate_random_hash()
        self.app_peer_data["cluster-set-domain-name"] = self.model.config.get(
            "cluster-set-name", f"cluster-set-{random_hash}"
        )

        logger.info("Recreating cluster")
        try:
            self.create_cluster()
            self.unit.status = ops.ActiveStatus(self.active_status_message)
            self.app.status = ops.ActiveStatus()
        except (MySQLCreateClusterError, MySQLCreateClusterSetError) as e:
            logger.exception("Failed to recreate cluster")
            event.fail(str(e))

    def create_cluster(self) -> None:
        """Create the MySQL InnoDB cluster on the unit.

        Should only be run by the leader unit.
        """
        self._mysql.create_cluster(self.unit_label)
        self._mysql.create_cluster_set()
        self._mysql.initialize_juju_units_operations_table()
        # rescan cluster for cleanup of unused
        # recovery users
        self._mysql.rescan_cluster()

        role = self._mysql.get_member_role()
        state = self._mysql.get_member_state()

        # TODO:
        #   Remove `.lower()` when migrating to MySQL 8.4
        #   (when breaking changes are allowed)
        self.unit_peer_data.update({
            "member-state": state.lower(),
            "member-role": role.lower(),
        })

    @abstractmethod
    def update_endpoints(self) -> None:
        """Update the endpoints for the cluster."""
        raise NotImplementedError

    def check_topology_timestamp_change(self, _) -> None:
        """Check for cluster topology changes and trigger endpoint update if needed.

        Used for trigger endpoint updates for non typical events like, add/remove unit
        or update status.
        """
        topology_change_set = {
            int(self.peers.data[unit]["topology-change-timestamp"])
            for unit in self.peers.units
            if self.peers.data[unit].get("topology-change-timestamp")
        }
        if not topology_change_set:
            # no topology change detected
            return
        topology_change = int(self.unit_peer_data.get("topology-change-timestamp", "0"))
        max_topology_change = max(topology_change_set)
        if self.unit.is_leader() and max_topology_change > topology_change:
            # update endpoints required
            self.update_endpoints()
            return

        # sync timestamp and trigger relation changed
        self.unit_peer_data.update({
            "topology-change-timestamp": str(max(max_topology_change, topology_change))
        })

    @property
    def peers(self) -> ops.model.Relation | None:
        """Retrieve the peer relation."""
        return self.model.get_relation(PEER)

    @property
    def cluster_initialized(self) -> bool:
        """Returns True if the cluster is initialized."""
        if not self.app_peer_data.get("cluster-name"):
            return False

        if self.unit_initialized():
            return True

        for unit in self.app_units:
            if unit == self.unit:
                continue
            try:
                if self._mysql.cluster_metadata_exists(self.get_unit_address(unit, PEER)):
                    return True
            except MySQLClusterMetadataExistsError:
                pass

        return False

    @property
    def only_one_cluster_node_thats_uninitialized(self) -> bool | None:
        """Check if only a single cluster node exists across all units."""
        if not self.app_peer_data.get("cluster-name"):
            return None

        total_cluster_nodes = 0
        for unit in self.app_units:
            total_cluster_nodes += self._mysql.get_cluster_node_count(
                from_instance=self.get_unit_address(unit, PEER)
            )

        total_online_cluster_nodes = 0
        for unit in self.app_units:
            total_online_cluster_nodes += self._mysql.get_cluster_node_count(
                from_instance=self.get_unit_address(unit, PEER),
                node_status=InstanceState.ONLINE,
            )

        return total_cluster_nodes == 1 and total_online_cluster_nodes == 0

    @property
    def cluster_fully_initialized(self) -> bool:
        """Returns True if the cluster is fully initialized.

        Fully initialized means that all unit that can be joined are joined.
        """
        return self._mysql.get_cluster_node_count(node_status=InstanceState.ONLINE) == min(
            GR_MAX_MEMBERS, self.app.planned_units()
        )

    @property
    def unit_configured(self) -> bool:
        """Check if the unit is configured to be part of the cluster."""
        return self._mysql.is_instance_configured_for_innodb(
            self.get_unit_address(self.unit, PEER),
        )

    @property
    def app_peer_data(self) -> ops.RelationDataContent | dict:
        """Application peer relation data object."""
        if self.peers is None:
            return {}

        return self.peers.data[self.app]

    @property
    def unit_peer_data(self) -> ops.RelationDataContent | dict:
        """Unit peer relation data object."""
        if self.peers is None:
            return {}

        return self.peers.data[self.unit]

    @property
    def app_units(self) -> set[Unit]:
        """The peer-related units in the application."""
        if not self.peers:
            return set()

        return {self.unit, *self.peers.units}

    @property
    def unit_label(self):
        """Return unit label."""
        return self.get_unit_label(self.unit)

    @property
    def _is_peer_data_set(self) -> bool:
        return bool(
            self.app_peer_data.get("cluster-name")
            and self.get_secret("app", ROOT_PASSWORD_KEY)
            and self.get_secret("app", SERVER_CONFIG_PASSWORD_KEY)
            and self.get_secret("app", CLUSTER_ADMIN_PASSWORD_KEY)
            and self.get_secret("app", MONITORING_PASSWORD_KEY)
            and self.get_secret("app", BACKUPS_PASSWORD_KEY)
        )

    @property
    def has_cos_relation(self) -> bool:
        """Returns a bool indicating whether a relation with COS is present."""
        cos_relations = self.model.relations.get(COS_AGENT_RELATION_NAME, [])
        active_cos_relations = list(
            filter(
                lambda relation: (
                    not (
                        isinstance(self.current_event, RelationBrokenEvent)
                        and self.current_event.relation.id == relation.id
                    )
                ),
                cos_relations,
            )
        )

        return len(active_cos_relations) > 0

    @property
    def active_status_message(self) -> str:
        """Active status message."""
        if self.unit_peer_data.get("member-role") != "primary":
            return ""

        if self._mysql.is_cluster_replica() is False:
            return "Primary"

        status = self._mysql.get_replica_cluster_status()
        if status == ClusterGlobalStatus.OK:
            return "Standby"
        else:
            return f"Standby ({status})"

    @property
    def removing_unit(self) -> bool:
        """Check if the unit is being removed."""
        return self.unit_peer_data.get("unit-status") == "removing"

    def unit_initialized(self, raise_exceptions: bool = False) -> bool:
        """Check if the unit is added to the cluster."""
        try:
            return self._mysql.cluster_metadata_exists()
        except MySQLClusterMetadataExistsError:
            if raise_exceptions:
                raise
            return False

    def peer_relation_data(self, scope: Scopes) -> DataPeerData:
        """Returns the peer relation data per scope."""
        if scope == APP_SCOPE:
            return self.peer_relation_app
        elif scope == UNIT_SCOPE:
            return self.peer_relation_unit

    def get_cluster_endpoints(self, relation_name: str) -> tuple[str, str, str]:
        """Return (rw, ro, offline) endpoints tuple names or IPs."""
        repl_topology = self._mysql.get_cluster_topology()
        repl_cluster = self._mysql.is_cluster_replica()

        if not repl_topology:
            raise MySQLGetClusterEndpointsError("Failed to get endpoints from cluster topology")

        unit_labels = {self.get_unit_label(unit): unit for unit in self.app_units}

        no_endpoints = set()
        ro_endpoints = set()
        rw_endpoints = set()

        for k, v in repl_topology.items():
            # When a replica instance is catching up with the primary instance,
            # the custom label assigned by the operator code has not yet been applied.
            if v["status"] == InstanceState.RECOVERING:
                continue

            address = f"{self.get_unit_address(unit_labels[k], relation_name)}:3306"

            if v["status"] != InstanceState.ONLINE:
                no_endpoints.add(address)
            if v["status"] == InstanceState.ONLINE and v["mode"] == "R/O":
                ro_endpoints.add(address)
            if v["status"] == InstanceState.ONLINE and v["mode"] == "R/W" and not repl_cluster:
                rw_endpoints.add(address)

        # Replica return global primary address
        if repl_cluster:
            primary_address = f"{self._mysql.get_cluster_global_primary_address()}:3306"
            rw_endpoints.add(primary_address)

        return ",".join(rw_endpoints), ",".join(ro_endpoints), ",".join(no_endpoints)

    def get_secret(self, scope: Scopes, key: str) -> str | None:
        """Get secret from the secret storage.

        Retrieve secret from juju secrets backend if secret exists there.
        Else retrieve from peer databag. This is to account for cases where secrets are stored in
        peer databag but the charm is then refreshed to a newer revision.
        """
        if scope not in get_args(Scopes):
            raise ValueError("Unknown secret scope")

        if not (peers := self.model.get_relation(PEER)):
            logger.warning("Peer relation unavailable.")
            return

        # NOTE: here we purposefully search both in secrets and in databag by using
        # the fetch_my_relation_field instead of peer_relation_data(scope).get_secrets().
        if (
            not (value := self.peer_relation_data(scope).fetch_my_relation_field(peers.id, key))
            and key in SECRET_KEY_FALLBACKS
        ):
            value = self.peer_relation_data(scope).fetch_my_relation_field(
                peers.id, SECRET_KEY_FALLBACKS[key]
            )
        return value

    def set_secret(self, scope: Scopes, key: str, value: str | None) -> None:
        """Set a secret in the secret storage."""
        if scope not in get_args(Scopes):
            raise MySQLSecretError(f"Invalid secret {scope=}")

        if scope == APP_SCOPE and not self.unit.is_leader():
            raise MySQLSecretError("Can only set app secrets on the leader unit")

        if not (peers := self.model.get_relation(PEER)):
            logger.warning("Peer relation unavailable.")
            return

        if not value:
            if key in SECRET_KEY_FALLBACKS:
                self.remove_secret(scope, SECRET_KEY_FALLBACKS[key])
            self.remove_secret(scope, key)
            return

        fallback_key_to_secret_key = {v: k for k, v in SECRET_KEY_FALLBACKS.items()}
        if key in fallback_key_to_secret_key:
            if self.peer_relation_data(scope).fetch_my_relation_field(peers.id, key):
                self.remove_secret(scope, key)
            self.peer_relation_data(scope).set_secret(
                peers.id, fallback_key_to_secret_key[key], value
            )
        else:
            self.peer_relation_data(scope).set_secret(peers.id, key, value)

    def remove_secret(self, scope: Scopes, key: str) -> None:
        """Removing a secret."""
        if scope not in get_args(Scopes):
            raise RuntimeError("Unknown secret scope.")

        if peers := self.model.get_relation(PEER):
            self.peer_relation_data(scope).delete_relation_data(peers.id, [key])
        else:
            logger.warning("Peer relation unavailable.")

    @staticmethod
    def generate_random_hash() -> str:
        """Generate a hash based on a random string.

        Returns:
            A hash based on a random string.
        """
        random_characters = generate_random_password(10)
        # TODO Should we be using md5 here?
        return hashlib.md5(random_characters.encode("utf-8")).hexdigest()  # noqa: S324


class MySQLBase(ABC):
    """Abstract class to encapsulate all operations related to the MySQL workload.

    This class handles the configuration of MySQL instances, and also the
    creation and configuration of MySQL InnoDB clusters via Group Replication.
    Some methods are platform specific and must be implemented in the related
    charm code.
    """

    def __init__(
        self,
        instance_address: str,
        socket_path: str,
        cluster_name: str,
        cluster_set_name: str,
        root_password: str,
        server_config_user: str,
        server_config_password: str,
        cluster_admin_user: str,
        cluster_admin_password: str,
        monitoring_user: str,
        monitoring_password: str,
        backups_user: str,
        backups_password: str,
        mysqlsh_path: str,
        executor_class: Type[BaseExecutor],
    ):
        """Initialize the MySQL class."""
        self.instance_address = instance_address
        self.socket_path = socket_path
        self.cluster_name = cluster_name
        self.cluster_set_name = cluster_set_name
        self.root_user = ROOT_USERNAME
        self.root_password = root_password
        self.server_config_user = server_config_user
        self.server_config_password = server_config_password
        self.cluster_admin_user = cluster_admin_user
        self.cluster_admin_password = cluster_admin_password
        self.monitoring_user = monitoring_user
        self.monitoring_password = monitoring_password
        self.backups_user = backups_user
        self.backups_password = backups_password
        self.mysqlsh_path = mysqlsh_path
        self.executor_class = executor_class
        self.passwords = [
            self.root_password,
            self.server_config_password,
            self.cluster_admin_password,
            self.monitoring_password,
            self.backups_password,
        ]

        self._auth_query_builder = CharmAuthorizationQueryBuilder(
            role_admin=ROLE_DBA,
            role_backup=ROLE_BACKUP,
            role_ddl=ROLE_DDL,
            role_stats=ROLE_STATS,
            role_reader=ROLE_READ,
            role_writer=ROLE_DML,
        )
        self._lock_query_builder = CharmLockingQueryBuilder(
            table_schema="mysql",
            table_name="juju_units_operations",
        )
        self._log_query_builder = CharmLoggingQueryBuilder()

        self._quoter = StringQueryQuoter()
        self._cluster_client_tcp = MySQLClusterClient(
            self._build_cluster_tcp_executor(instance_address),
        )
        self._instance_client_tcp = MySQLInstanceClient(
            self._build_instance_tcp_executor(instance_address),
            self._quoter,
        )
        self._instance_client_sock = MySQLInstanceClient(
            self._build_instance_sock_executor(),
            self._quoter,
        )

    def _build_cluster_tcp_executor(self, host: str, port: int = 3306):
        """Build a TCP executor for the cluster operations."""
        return self.executor_class(
            conn_details=ConnectionDetails(
                username=self.cluster_admin_user,
                password=self.cluster_admin_password,
                host=host,
                port=str(port),
            ),
            shell_path=self.mysqlsh_path,
        )

    def _build_instance_tcp_executor(self, host: str, port: int = ADMIN_PORT):
        """Build a TCP executor for the instance operations."""
        return self.executor_class(
            conn_details=ConnectionDetails(
                username=self.server_config_user,
                password=self.server_config_password,
                host=host,
                port=str(port),
            ),
            shell_path=self.mysqlsh_path,
        )

    def _build_instance_sock_executor(self):
        """Build a socket executor for the instance operations."""
        return self.executor_class(
            conn_details=ConnectionDetails(
                username=self.root_user,
                password=self.root_password,
                socket=self.socket_path,
            ),
            shell_path=self.mysqlsh_path,
        )

    def render_mysqld_configuration(  # noqa: C901
        self,
        *,
        profile: str,
        audit_log_enabled: bool,
        audit_log_strategy: str,
        audit_log_policy: str,
        memory_limit: int | None = None,
        experimental_max_connections: int | None = None,
        binlog_retention_days: int,
        snap_common: str = "",
    ) -> tuple[str, dict]:
        """Render mysqld ini configuration file."""
        max_connections = None
        performance_schema_instrument = ""
        if profile == "testing":
            innodb_buffer_pool_size = 20 * BYTES_1MiB
            innodb_buffer_pool_chunk_size = 1 * BYTES_1MiB
            group_replication_message_cache_size = 128 * BYTES_1MiB
            max_connections = 100
            performance_schema_instrument = "'memory/%=OFF'"
        else:
            available_memory = self.get_available_memory()
            if memory_limit:
                # when memory limit is set, we need to use the minimum
                # between the available memory and the limit
                available_memory = min(available_memory, memory_limit)

            if experimental_max_connections:
                # when set, we use the experimental max connections
                # and it takes precedence over buffers usage
                max_connections = experimental_max_connections
                # we reserve 200MiB for memory buffers
                # even when there's some overcommittment
                available_memory = max(
                    available_memory - max_connections * 12 * BYTES_1MiB,
                    200 * BYTES_1MiB,
                )

            (
                innodb_buffer_pool_size,
                innodb_buffer_pool_chunk_size,
                group_replication_message_cache_size,
            ) = self.get_innodb_buffer_pool_parameters(available_memory)

            # constrain max_connections based on the available memory
            # after innodb_buffer_pool_size calculation
            available_memory -= innodb_buffer_pool_size + (
                group_replication_message_cache_size or 0
            )
            if not max_connections:
                max_connections = max(
                    self.get_max_connections(available_memory), MAX_CONNECTIONS_FLOOR
                )

            if available_memory < 2 * BYTES_1GiB:
                # disable memory instruments if we have less than 2GiB of RAM
                performance_schema_instrument = "'memory/%=OFF'"

        binlog_retention_seconds = binlog_retention_days * 24 * 60 * 60
        config = configparser.ConfigParser(interpolation=None)

        # do not enable slow query logs, but specify a log file path in case
        # the admin enables them manually
        config["mysqld"] = {
            # All interfaces bind expected
            "bind_address": "0.0.0.0",  # noqa: S104
            "mysqlx_bind_address": "0.0.0.0",  # noqa: S104
            "admin_address": self.instance_address,
            "report_host": self.instance_address,
            "max_connections": max_connections,
            "innodb_buffer_pool_size": innodb_buffer_pool_size,
            "log_error_services": "log_filter_internal;log_sink_internal",
            "log_error": f"{snap_common}/var/log/mysql/error.log",
            "general_log": "OFF",
            "general_log_file": f"{snap_common}/var/log/mysql/general.log",
            "loose-group_replication_paxos_single_leader": "ON",
            "slow_query_log_file": f"{snap_common}/var/log/mysql/slow.log",
            "binlog_expire_logs_seconds": f"{binlog_retention_seconds}",
            "loose-audit_log_policy": audit_log_policy.upper(),
            "loose-audit_log_file": f"{snap_common}/var/log/mysql/audit.log",
            "gtid_mode": "ON",
            "enforce_gtid_consistency": "ON",
            "activate_all_roles_on_login": "ON",
            "max_connect_errors": "10000",
        }

        if audit_log_enabled:
            # This is used for being able to know the current state of the
            # audit plugin on config changes
            config["mysqld"]["loose-audit_log_format"] = "JSON"
        if audit_log_strategy == "async":
            config["mysqld"]["loose-audit_log_strategy"] = "ASYNCHRONOUS"
        else:
            config["mysqld"]["loose-audit_log_strategy"] = "SEMISYNCHRONOUS"

        if innodb_buffer_pool_chunk_size:
            config["mysqld"]["innodb_buffer_pool_chunk_size"] = str(innodb_buffer_pool_chunk_size)
        if performance_schema_instrument:
            config["mysqld"]["performance-schema-instrument"] = performance_schema_instrument
        if group_replication_message_cache_size:
            config["mysqld"]["loose-group_replication_message_cache_size"] = str(
                group_replication_message_cache_size
            )

        with io.StringIO() as string_io:
            config.write(string_io)
            return string_io.getvalue(), dict(config["mysqld"])

    def _build_mysql_database_dba_role(self, database: str) -> str:
        """Builds the database-level DBA role, given length constraints."""
        role_prefix = "charmed_dba"
        role_suffix = "XX"

        role_name_available = ROLE_MAX_LENGTH - len(role_prefix) - len(role_suffix) - 2
        role_name_description = database[:role_name_available]
        role_name_collisions = self._instance_client_tcp.search_instance_roles(
            name_pattern=f"{role_prefix}_{role_name_description}_%"
        )

        return "_".join((
            role_prefix,
            role_name_description,
            str(len(role_name_collisions)).zfill(len(role_suffix)),
        ))

    def _plugin_file_exists(self, file_name: str) -> bool:
        """Check if the plugin file exists."""
        path = self._instance_client_tcp.get_instance_variable(Scope.GLOBAL, "plugin_dir")
        return self._file_exists(f"{path}/{file_name}")

    @contextmanager
    def _read_only_disabled(self) -> Generator:
        """Temporarily disables the super-read-only mode."""
        value = self._instance_client_tcp.get_instance_variable(Scope.GLOBAL, "super_read_only")

        try:
            self._instance_client_tcp.set_instance_variable(Scope.GLOBAL, "super_read_only", "OFF")
            yield
        finally:
            self._instance_client_tcp.set_instance_variable(Scope.GLOBAL, "super_read_only", value)

    def configure_mysql_router_roles(self) -> None:
        """Configure the MySQL Router roles for the instance."""
        try:
            router_roles = self._instance_client_sock.search_instance_roles("%router")
            router_roles = [role.rolename for role in router_roles]
        except ExecutionError as e:
            raise MySQLConfigureMySQLRolesError() from e

        executor = self._build_instance_sock_executor()

        for role in (LEGACY_ROLE_ROUTER, MODERN_ROLE_ROUTER):
            if role in router_roles:
                continue

            logger.debug(f"Missing MySQL role {role}")
            configure_role_commands = ";".join([
                f"CREATE ROLE {role}",
                f"GRANT CREATE ON *.* TO {role}",
                f"GRANT CREATE USER ON *.* TO {role}",
                # The granting of all privileges to the MySQL Router role
                # can only be restricted when the privileges to the users
                # created by such role are restricted as well
                # https://github.com/canonical/mysql-router-operator/blob/main/src/mysql_shell/__init__.py#L134-L136
                f"GRANT ALL ON *.* TO {role} WITH GRANT OPTION",
            ])

            try:
                logger.debug(f"Configuring Router role for {self.instance_address}")
                executor.execute_sql(configure_role_commands)
            except ExecutionError as e:
                logger.error(f"Failed to configure Router role for {self.instance_address}")
                raise MySQLConfigureMySQLRolesError() from e

    def configure_mysql_system_roles(self) -> None:
        """Configure the MySQL system roles for the instance."""
        auth_roles = {
            ROLE_DBA,
            ROLE_BACKUP,
            ROLE_DDL,
            ROLE_DML,
            ROLE_READ,
            ROLE_STATS,
        }

        try:
            existing_roles = self._instance_client_sock.search_instance_roles("charmed_%")
            existing_roles = {role.rolename for role in existing_roles}
        except ExecutionError as e:
            raise MySQLConfigureMySQLRolesError() from e

        if not (auth_roles - existing_roles):
            return

        logger.debug("Missing MySQL roles")
        query = self._auth_query_builder.build_instance_auth_roles_query()
        executor = self._build_instance_sock_executor()

        try:
            logger.debug(f"Configuring MySQL roles for {self.instance_address}")
            executor.execute_sql(query)
        except ExecutionError as e:
            logger.error(f"Failed to configure roles for {self.instance_address}")
            raise MySQLConfigureMySQLRolesError() from e

    def configure_mysql_system_users(self) -> None:
        """Configure the MySQL system users for the instance."""
        configure_users_commands = [
            f"UPDATE mysql.user SET authentication_string=null WHERE User='{self.root_user}' and Host='localhost'",  # noqa: S608
            f"ALTER USER '{self.root_user}'@'localhost' IDENTIFIED BY '{self.root_password}'",
            f"CREATE USER '{self.server_config_user}'@'%' IDENTIFIED BY '{self.server_config_password}'",
            f"CREATE USER '{self.monitoring_user}'@'%' IDENTIFIED BY '{self.monitoring_password}' WITH MAX_USER_CONNECTIONS 3",
            f"CREATE USER '{self.backups_user}'@'%' IDENTIFIED BY '{self.backups_password}'",
        ]

        # SYSTEM_USER and SUPER privileges to revoke from the root users
        # Reference: https://dev.mysql.com/doc/refman/8.0/en/privileges-provided.html#priv_super
        configure_privs_commands = [
            f"GRANT ALL ON *.* TO '{self.server_config_user}'@'%' WITH GRANT OPTION",
            f"GRANT charmed_stats TO '{self.monitoring_user}'@'%'",
            f"GRANT charmed_backup TO '{self.backups_user}'@'%'",
            f"REVOKE BINLOG_ADMIN, CONNECTION_ADMIN, ENCRYPTION_KEY_ADMIN, GROUP_REPLICATION_ADMIN, REPLICATION_SLAVE_ADMIN, SET_USER_ID, SUPER, SYSTEM_USER, SYSTEM_VARIABLES_ADMIN, VERSION_TOKEN_ADMIN ON *.* FROM '{self.root_user}'@'localhost'",
            "FLUSH PRIVILEGES",
        ]

        configure_commands = ";".join([
            *configure_users_commands,
            *configure_privs_commands,
        ])

        executor = self._build_instance_sock_executor()

        try:
            logger.debug(f"Configuring MySQL users for {self.instance_address}")
            executor.execute_sql(configure_commands)
        except ExecutionError as e:
            logger.error(f"Failed to configure users for: {self.instance_address}")
            raise MySQLConfigureMySQLUsersError from e

    def install_plugins(self, plugins: list[str]) -> None:
        """Install extra plugins."""
        # TODO:
        #   Remove this context-manager when migrating to MySQL 8.4
        #   (when breaking changes are allowed)
        with self._read_only_disabled():
            installed_plugins = self._instance_client_tcp.search_instance_plugins("%")

            for plugin in plugins:
                plugin_path = ALLOWED_PLUGINS.get(plugin)
                if not self._plugin_file_exists(plugin_path):
                    logger.warning(f"{plugin=} file not found. Skip installation")
                    continue

                if plugin in installed_plugins:
                    logger.info(f"{plugin=} already installed")
                    continue
                if plugin not in ALLOWED_PLUGINS:
                    logger.warning(f"{plugin=} is not supported")
                    continue

                try:
                    self._instance_client_tcp.install_instance_plugin(plugin, plugin_path)
                except ExecutionError as e:
                    raise MySQLPluginInstallError() from e

    def uninstall_plugins(self, plugins: list[str]) -> None:
        """Uninstall plugins."""
        # TODO:
        #   Remove this context-manager when migrating to MySQL 8.4
        #   (when breaking changes are allowed)
        with self._read_only_disabled():
            installed_plugins = self._instance_client_tcp.search_instance_plugins("%")

            for plugin in plugins:
                if plugin not in installed_plugins:
                    logger.info(f"{plugin=} not installed")
                    continue

                try:
                    self._instance_client_tcp.uninstall_instance_plugin(plugin)
                except ExecutionError as e:
                    raise MySQLPluginInstallError() from e

    def does_mysql_user_exist(self, username: str, hostname: str) -> bool:
        """Checks if a mysql user already exists."""
        try:
            searched_users = self._instance_client_tcp.search_instance_users(username)
        except ExecutionError as e:
            raise MySQLCheckUserExistenceError() from e

        for user in searched_users:
            if user.username == username and user.hostname == hostname:
                return True

        return False

    def configure_mysqlrouter_user(
        self,
        username: str,
        password: str,
        hostname: str,
        unit_name: str,
    ) -> None:
        """Configure a mysqlrouter user and grant the appropriate permissions to the user."""
        primary_address = self.get_cluster_primary_address()
        primary_executor = self._build_instance_tcp_executor(primary_address)

        escaped_user_attributes = json.dumps({"unit_name": unit_name}).replace('"', r"\"")
        queries = ";".join([
            f"CREATE USER '{username}'@'{hostname}' IDENTIFIED BY '{password}' ATTRIBUTE '{escaped_user_attributes}'",
            f"GRANT CREATE USER ON *.* TO '{username}'@'{hostname}' WITH GRANT OPTION",
            f"GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE ON mysql_innodb_cluster_metadata.* TO '{username}'@'{hostname}'",
            f"GRANT SELECT ON mysql.user TO '{username}'@'{hostname}'",
            f"GRANT SELECT ON performance_schema.replication_group_members TO '{username}'@'{hostname}'",
            f"GRANT SELECT ON performance_schema.replication_group_member_stats TO '{username}'@'{hostname}'",
            f"GRANT SELECT ON performance_schema.global_variables TO '{username}'@'{hostname}'",
        ])

        try:
            logger.debug(f"Configuring MySQLRouter {username=}")
            primary_executor.execute_sql(queries)
        except ExecutionError as e:
            logger.error(f"Failed to configure mysqlrouter {username=}")
            raise MySQLConfigureRouterUserError() from e

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(MySQLCreateApplicationDatabaseError),
    )
    def create_database(self, database: str) -> None:
        """Create an application database."""
        if database in self.get_non_system_databases():
            return

        primary_address = self.get_cluster_primary_address()
        primary_executor = self._build_instance_tcp_executor(primary_address)

        role_name = self._build_mysql_database_dba_role(database)
        role_query = self._auth_query_builder.build_database_admin_role_query(role_name, database)

        queries = ";".join([
            f"CREATE DATABASE `{database}`",
            f"GRANT SELECT ON `{database}`.* TO '{ROLE_READ}'",
            f"GRANT SELECT, INSERT, DELETE, UPDATE ON `{database}`.* TO '{ROLE_DML}'",
            role_query,
        ])

        try:
            logger.info(f"Creating application {database=} and DBA {role_name=}")
            primary_executor.execute_sql(queries)
        except ExecutionError as e:
            logger.error(f"Failed to create application database {database}")
            raise MySQLCreateApplicationDatabaseError() from e

    def create_scoped_user(
        self,
        database: str,
        username: str,
        password: str,
        hostname: str,
        *,
        unit_name: str | None = None,
        extra_roles: list[str] | None = None,
    ) -> None:
        """Create an application user scoped to the created database."""
        attributes = {}
        if unit_name is not None:
            attributes = {"unit_name": unit_name}
        if extra_roles is None:
            extra_roles = []

        if set(extra_roles) & FORBIDDEN_EXTRA_ROLES:
            logger.error(f"Invalid extra user roles: {extra_roles}")
            raise MySQLCreateApplicationScopedUserError("invalid role(s) for extra user roles")

        primary_address = self.get_cluster_primary_address()
        primary_executor = self._build_instance_tcp_executor(primary_address)
        primary_client = MySQLInstanceClient(primary_executor, self._quoter)

        user = User(username, hostname, attributes)

        try:
            primary_client.create_instance_user(user, password, extra_roles)
            if not extra_roles:
                primary_executor.execute_sql(
                    ";".join([
                        f"GRANT USAGE ON *.* TO `{username}`@`{hostname}`",
                        f"GRANT ALL PRIVILEGES ON `{database}`.* TO `{username}`@`{hostname}`",
                    ])
                )
        except ExecutionError as e:
            logger.error(f"Failed to create application scoped user {username}@{hostname}")
            raise MySQLCreateApplicationScopedUserError() from e

    def get_mysql_router_users_for_unit(
        self,
        *,
        relation_id: int,
        mysql_router_unit_name: str,
    ) -> list[User]:
        """Get users for related MySQL Router unit."""
        user_attrs = {
            "created_by_user": f"relation-{relation_id}",
            "created_by_juju_unit": mysql_router_unit_name,
        }

        try:
            users = self._instance_client_tcp.search_instance_users("%", user_attrs)
        except ExecutionError as e:
            raise MySQLGetRouterUsersError() from e
        else:
            return users

    def delete_users_for_unit(self, unit_name: str) -> None:
        """Delete users for a unit."""
        primary_address = self.get_cluster_primary_address()
        primary_executor = self._build_instance_tcp_executor(primary_address)
        primary_client = MySQLInstanceClient(primary_executor, self._quoter)

        try:
            primary_client.delete_instance_users(
                primary_client.search_instance_users("%", {"unit_name": unit_name}),
            )
        except ExecutionError as e:
            raise MySQLDeleteUsersForUnitError() from e

    def delete_users_for_relation(self, username: str) -> None:
        """Delete users for a relation."""
        primary_address = self.get_cluster_primary_address()
        primary_executor = self._build_instance_tcp_executor(primary_address)
        primary_client = MySQLInstanceClient(primary_executor, self._quoter)

        user = User(username, "%")

        try:
            primary_client.delete_instance_user(user)
            primary_client.delete_instance_users(
                primary_client.search_instance_users("%", {"created_by_user": username}),
            )
        except ExecutionError as e:
            raise MySQLDeleteUsersForRelationError() from e

    def delete_user(self, username: str) -> None:
        """Delete user."""
        primary_address = self.get_cluster_primary_address()
        primary_executor = self._build_instance_tcp_executor(primary_address)
        primary_client = MySQLInstanceClient(primary_executor, self._quoter)

        user = User(username, "%")

        try:
            primary_client.delete_instance_user(user)
        except ExecutionError as e:
            raise MySQLDeleteUserError() from e

    def remove_router_from_cluster_metadata(self, router_id: str) -> None:
        """Remove MySQL Router from InnoDB Cluster metadata."""
        router_name, router_mode = router_id.split("::")

        try:
            self._cluster_client_tcp.remove_router_from_cluster(
                cluster_name=self.cluster_name,
                router_name=router_name,
                router_mode=router_mode,
            )
        except ExecutionError as e:
            raise MySQLRemoveRouterFromMetadataError() from e

    def set_dynamic_variable(
        self,
        variable: str,
        value: Any,
        instance_address: str | None = None,
    ) -> None:
        """Set a dynamic variable value for the instance."""
        if not instance_address:
            instance_address = self.instance_address

        client = MySQLInstanceClient(
            executor=self._build_instance_tcp_executor(instance_address),
            quoter=self._quoter,
        )

        try:
            client.set_instance_variable(Scope.GLOBAL, variable, value)
        except ExecutionError as e:
            raise MySQLSetVariableError() from e

    def configure_instance(self, create_cluster_admin: bool = True) -> None:
        """Configure the instance to be used in an InnoDB cluster.

        Args:
            create_cluster_admin: Whether to create the cluster admin user.
        """
        options = {
            "restart": "true",
        }

        if create_cluster_admin:
            options.update({
                "clusterAdmin": self.cluster_admin_user,
                "clusterAdminPassword": self.cluster_admin_password,
            })

        client = MySQLClusterClient(
            executor=self._build_instance_tcp_executor(self.instance_address),
        )

        try:
            client.setup_instance_before_cluster(options=options)
        except ExecutionError as e:
            raise MySQLConfigureInstanceError() from e

    def create_cluster(self, unit_label: str) -> None:
        """Create an InnoDB cluster with Group Replication enabled."""
        # defaulting group replication communication stack to MySQL instead of XCOM
        # since it will encrypt gr members communication by default
        options = {
            "communicationStack": "MySQL",
        }

        try:
            self._cluster_client_tcp.create_cluster(
                cluster_name=self.cluster_name,
                options=options,
            )
            self._cluster_client_tcp.update_instance_within_cluster(
                cluster_name=self.cluster_name,
                instance_host=self.instance_address,
                instance_port=str(3306),
                options={"label": unit_label},
            )
        except ExecutionError as e:
            raise MySQLCreateClusterError() from e

    def create_cluster_set(self) -> None:
        """Create a cluster set for the cluster on cluster primary."""
        try:
            self._cluster_client_tcp.create_cluster_set(
                cluster_name=self.cluster_name,
                cluster_set_name=self.cluster_set_name,
            )
        except ExecutionError as e:
            raise MySQLCreateClusterSetError() from e

    def create_replica_cluster(
        self,
        endpoint: str,
        replica_cluster_name: str,
        instance_label: str,
        donor: str | None = None,
        method: str | None = "auto",
    ) -> None:
        """Create a replica cluster from the primary cluster."""
        options = {
            "recoveryProgress": 0,
            "recoveryMethod": method,
            "timeout": 0,
            "communicationStack": "MySQL",
        }

        if donor:
            options["cloneDonor"] = donor

        host = endpoint.split(":")[0]
        port = str(3306)

        try:
            self._cluster_client_tcp.create_cluster_set_replica(
                cluster_name=replica_cluster_name,
                source_host=host,
                source_port=port,
                options=options,
            )
            self._cluster_client_tcp.update_instance_within_cluster(
                cluster_name=replica_cluster_name,
                instance_host=host,
                instance_port=port,
                options={"label": instance_label},
            )
        except ExecutionError as e:
            if method == "clone":
                raise MySQLCreateReplicaClusterError() from e

            logger.warning("Failed to create replica cluster. Fallback to clone method")
            self.create_replica_cluster(
                endpoint=endpoint,
                replica_cluster_name=replica_cluster_name,
                instance_label=instance_label,
                donor=donor,
                method="clone",
            )

    def promote_cluster_to_primary(self, cluster_name: str, force: bool = False) -> None:
        """Promote a cluster to become the primary cluster on the cluster set."""
        try:
            self._cluster_client_tcp.promote_cluster_set_replica(
                cluster_name=cluster_name,
                force=force,
            )
        except ExecutionError as e:
            raise MySQLPromoteClusterToPrimaryError() from e

    def is_cluster_in_cluster_set(self, cluster_name: str) -> bool | None:
        """Check if a cluster is in the cluster set."""
        cs_status = self._cluster_client_tcp.fetch_cluster_set_status(extended=False)
        if cs_status is None:
            return None

        return cluster_name in cs_status["clusters"]

    def cluster_metadata_exists(self, from_instance: str | None = None) -> bool:
        """Check if this cluster metadata exists on database.

        Use mysqlsh when querying clusters from remote instances. However, use
        mysqlcli when querying locally since this method can be called before
        the cluster is initialized (before serverconfig and root users are set up
        correctly)
        """
        if from_instance:
            client = MySQLInstanceClient(
                self._build_instance_tcp_executor(from_instance),
                self._quoter,
            )
        else:
            client = MySQLInstanceClient(
                self._build_instance_sock_executor(),
                self._quoter,
            )

        try:
            labels = client.get_cluster_labels()
        except ExecutionError as e:
            raise MySQLClusterMetadataExistsError() from e

        return self.cluster_name in labels

    def rejoin_cluster(self, cluster_name: str) -> None:
        """Try to rejoin a cluster to the cluster set."""
        try:
            self._cluster_client_tcp.rejoin_cluster_set_cluster(cluster_name)
        except ExecutionError as e:
            raise MySQLRejoinClusterError() from e

    def remove_replica_cluster(self, replica_cluster_name: str, force: bool = False) -> None:
        """Remove a replica cluster from the cluster-set."""
        options = {"force": str(force)}

        try:
            self._cluster_client_tcp.remove_cluster_set_replica(
                cluster_name=replica_cluster_name,
                options=options,
            )
        except ExecutionError as e:
            raise MySQLRemoveReplicaClusterError() from e

    def initialize_juju_units_operations_table(self) -> None:
        """Initialize the mysql.juju_units_operations table using the serverconfig user."""
        query = self._lock_query_builder.build_table_creation_query()
        executor = self._build_instance_tcp_executor(self.instance_address)

        try:
            logger.debug("Initializing the mysql.juju_units_operations table")
            executor.execute_sql(query)
        except ExecutionError as e:
            logger.error("Failed to initialize the mysql.juju_units_operations table")
            raise MySQLInitializeJujuOperationsTableError() from e

    def add_instance_to_cluster(
        self,
        *,
        instance_address: str,
        instance_unit_label: str,
        from_instance: str | None = None,
        lock_instance: str | None = None,
        method: str = "auto",
    ) -> None:
        """Add an instance to the InnoDB cluster."""
        if not from_instance:
            from_instance = self.instance_address
        if not lock_instance:
            lock_instance = from_instance

        options = {
            "recoveryMethod": method,
            "label": instance_unit_label,
        }

        locking_executor = self._build_instance_tcp_executor(lock_instance)
        connect_executor = self._build_cluster_tcp_executor(from_instance)
        client = MySQLClusterClient(connect_executor)

        if not self._acquire_lock(
            executor=locking_executor,
            unit_label=instance_unit_label,
            unit_task=CharmLockingQueryBuilder.INSTANCE_ADDITION_TASK,
        ):
            raise MySQLLockAcquisitionError("Lock not acquired")

        try:
            client.attach_instance_into_cluster(
                cluster_name=self.cluster_name,
                instance_host=instance_address,
                instance_port=str(3306),
                options=options,
            )
        except ExecutionError as e:
            if method == "clone":
                raise MySQLAddInstanceToClusterError() from e

            logger.warning("Failed to add instance to cluster. Fallback to clone method")
            self.add_instance_to_cluster(
                instance_address=instance_address,
                instance_unit_label=instance_unit_label,
                from_instance=from_instance,
                lock_instance=lock_instance,
                method="clone",
            )
        finally:
            self._release_lock(
                executor=locking_executor,
                unit_label=instance_unit_label,
                unit_task=CharmLockingQueryBuilder.INSTANCE_ADDITION_TASK,
            )

    def rejoin_instance_to_cluster(
        self,
        *,
        unit_address: str,
        unit_label: str,
        from_instance: str | None = None,
    ) -> None:
        """Rejoin an instance to the InnoDB cluster.

        Args:
            unit_address: The address of the unit to rejoin.
            unit_label: The label of the unit to rejoin.
            from_instance: The instance from which to rejoin the cluster.
        """
        if not from_instance:
            from_instance = self.instance_address

        executor = self._build_cluster_tcp_executor(from_instance)
        client = MySQLClusterClient(executor)

        if not self._acquire_lock(
            executor=executor,
            unit_label=unit_label,
            unit_task=CharmLockingQueryBuilder.INSTANCE_ADDITION_TASK,
        ):
            raise MySQLLockAcquisitionError("Lock not acquired")

        try:
            client.rejoin_instance_into_cluster(
                cluster_name=self.cluster_name,
                instance_host=unit_address,
                instance_port=str(3306),
            )
        except ExecutionError as e:
            raise MySQLRejoinInstanceToClusterError() from e
        finally:
            self._release_lock(
                executor=executor,
                unit_label=unit_label,
                unit_task=CharmLockingQueryBuilder.INSTANCE_ADDITION_TASK,
            )

    def is_instance_configured_for_innodb(self, instance_address: str) -> bool:
        """Confirm if instance is configured for use in an InnoDB cluster."""
        client = MySQLClusterClient(
            executor=self._build_instance_tcp_executor(instance_address),
        )

        try:
            result = client.check_instance_before_cluster()
        except ExecutionError:
            return False
        else:
            return result["status"] == "ok"

    def are_locks_acquired(self, from_instance: str, task_name: str) -> bool:
        """Report if any topology change is being executed."""
        query = self._lock_query_builder.build_fetch_acquired_query(task_name)
        executor = self._build_instance_tcp_executor(from_instance)

        try:
            logger.debug(f"Fetching acquired lock {task_name}")
            locks = executor.execute_sql(query)
        except ExecutionError:
            logger.error(f"Failed to fetch acquired lock {task_name}")
            return True
        else:
            return len(locks) == 1

    def rescan_cluster(
        self,
        from_instance: str | None = None,
        remove_instances: bool = False,
        add_instances: bool = False,
    ) -> None:
        """Rescan the cluster for topology changes."""
        if not from_instance:
            from_instance = self.instance_address

        client = MySQLClusterClient(
            executor=self._build_cluster_tcp_executor(from_instance),
        )

        options = {}
        if remove_instances:
            options["removeInstances"] = "auto"
        if add_instances:
            options["addInstances"] = "auto"

        try:
            client.rescan_cluster(cluster_name=self.cluster_name, options=options)
        except ExecutionError as e:
            raise MySQLRescanClusterError() from e

    def is_instance_in_cluster(self, unit_label: str) -> bool:
        """Confirm if instance is in the cluster."""
        try:
            if not self.cluster_metadata_exists():
                return False
        except MySQLClusterMetadataExistsError:
            return False

        try:
            cluster_status = self._cluster_client_tcp.fetch_cluster_status(
                cluster_name=self.cluster_name,
                extended=False,
            )
        except ExecutionError:
            return False
        else:
            unit_spec = cluster_status["defaultReplicaSet"]["topology"].get(unit_label, {})
            unit_status = unit_spec.get("status")
            return unit_status in (InstanceState.ONLINE, InstanceState.RECOVERING)

    def instance_belongs_to_cluster(self, unit_label: str) -> bool:
        """Check if instance belongs to cluster independently of current state.

        Args:
            unit_label: The label of the unit to check.
        """
        try:
            labels = self._instance_client_tcp.get_cluster_instance_labels(self.cluster_name)
        except ExecutionError:
            return False
        else:
            return unit_label in labels

    @retry(
        wait=wait_fixed(2),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(ExecutionError),
    )
    def get_cluster_status(
        self, from_instance: str | None = None, extended: bool | None = False
    ) -> dict | None:
        """Get the cluster status dictionary."""
        if not from_instance:
            from_instance = self.instance_address

        client = MySQLClusterClient(
            executor=self._build_cluster_tcp_executor(from_instance),
        )

        try:
            status = client.fetch_cluster_status(self.cluster_name, extended)
        except ExecutionError:
            return None
        else:
            return status

    def get_cluster_set_status(
        self, from_instance: str | None = None, extended: int | None = 1
    ) -> dict | None:
        """Get the cluster-set status dictionary."""
        if not from_instance:
            from_instance = self.instance_address

        client = MySQLClusterClient(
            executor=self._build_cluster_tcp_executor(from_instance),
        )

        try:
            status = client.fetch_cluster_set_status(bool(extended))
        except ExecutionError:
            return None
        else:
            return status

    def get_cluster_names(self) -> set[str]:
        """Get the names of the clusters in the cluster set."""
        cluster_set_status = self.get_cluster_set_status()
        if not cluster_set_status:
            return set()

        return set(cluster_set_status["clusters"])

    def get_replica_cluster_status(self, replica_cluster_name: str | None = None) -> str:
        """Get the replica cluster status."""
        if not replica_cluster_name:
            replica_cluster_name = self.cluster_name

        cluster_set_status = self.get_cluster_set_status()
        if not cluster_set_status:
            return ClusterGlobalStatus.UNKNOWN

        cluster_spec = cluster_set_status["clusters"].get(replica_cluster_name)
        if not cluster_spec:
            return ClusterGlobalStatus.UNKNOWN

        return cluster_spec["globalStatus"]

    def get_cluster_node_count(
        self,
        from_instance: str | None = None,
        node_status: InstanceState | None = None,
    ) -> int:
        """Retrieve current count of cluster nodes, optionally filtered by status."""
        from_instance = from_instance if from_instance else self.instance_address
        node_statuses = [node_status] if node_status else None

        client = MySQLInstanceClient(
            executor=self._build_instance_tcp_executor(from_instance),
            quoter=self._quoter,
        )

        try:
            status = client.search_instance_replication_members(states=node_statuses)
        except ExecutionError:
            logger.warning("Failed to get node count")
            return 0
        else:
            return len(status)

    @retry(
        retry=retry_if_exception_type(MySQLLockAcquisitionError),
        stop=stop_after_attempt(15),
        reraise=True,
        wait=wait_random(min=4, max=30),
    )
    def remove_instance(
        self,
        unit_label: str,
        from_instance: str | None = None,
        lock_instance: str | None = None,
        auto_dissolve: bool | None = True,
    ) -> None:
        """Remove instance from the cluster.

        This method is called from each unit being torn down, thus we must obtain
        locks on the cluster primary. There is a retry mechanism for any issues
        obtaining the lock, removing instances/dissolving the cluster, or releasing
        the lock.

        Args:
            unit_label: The label of the unit to remove.
            from_instance: (optional) The instance address to execute the commands on.
            lock_instance: (optional) The instance address to acquire the lock on.
            auto_dissolve: (optional) Whether to automatically dissolve the cluster
                if this is the last instance in the cluster.
        """
        if self.get_cluster_node_count() == 1:
            self.dissolve_cluster(auto_dissolve)
            return

        if not from_instance:
            from_instance = self.get_cluster_primary_address()
        if not lock_instance:
            lock_instance = from_instance

        options = {
            "force": "true",
        }

        locking_executor = self._build_instance_tcp_executor(lock_instance)
        connect_executor = self._build_cluster_tcp_executor(from_instance)
        client = MySQLClusterClient(connect_executor)

        if not self._acquire_lock(
            executor=locking_executor,
            unit_label=unit_label,
            unit_task=CharmLockingQueryBuilder.INSTANCE_REMOVAL_TASK,
        ):
            raise MySQLLockAcquisitionError("Lock not acquired")

        # Get remaining cluster member addresses before removing instance
        member_addresses = self._get_cluster_member_addresses(
            exclude_units=[unit_label],
        )

        try:
            client.detach_instance_from_cluster(
                cluster_name=self.cluster_name,
                instance_host=self.instance_address,
                instance_port=str(3306),
                options=options,
            )
        except ExecutionError as e:
            raise MySQLRemoveInstanceError() from e
        finally:
            # Retrieve the cluster primary's address again (in case the old primary is scaled down)
            if member_addresses:
                primary_address = self.get_cluster_primary_address(member_addresses[0])
                locking_executor = self._build_instance_tcp_executor(primary_address)

            self._release_lock(
                executor=locking_executor,
                unit_label=unit_label,
                unit_task=CharmLockingQueryBuilder.INSTANCE_REMOVAL_TASK,
            )

    def dissolve_cluster(self, force: bool = True) -> None:
        """Dissolve the cluster independently of the unit teardown process."""
        cluster_names = self.get_cluster_names()

        if len(cluster_names) > 1 and not self.is_cluster_replica():
            another_cluster = (cluster_names - {self.cluster_name}).pop()
            self.promote_cluster_to_primary(another_cluster)
            self.remove_replica_cluster(self.cluster_name)

        if force:
            self._cluster_client_tcp.destroy_cluster(self.cluster_name, {"force": "true"})

    def _acquire_lock(self, executor: BaseExecutor, unit_label: str, unit_task: str) -> bool:
        """Attempts to acquire a lock by using the mysql.juju_units_operations table."""
        acquire_query = self._lock_query_builder.build_acquire_query(
            task=unit_task,
            instance=unit_label,
        )
        fetch_query = self._lock_query_builder.build_fetch_acquired_query(
            task=unit_task,
        )

        try:
            logger.debug(f"Attempting to acquire lock {unit_task} for unit {unit_label}")
            ____ = executor.execute_sql(acquire_query)
            rows = executor.execute_sql(fetch_query)
        except ExecutionError:
            logger.debug(f"Failed to acquire lock {unit_task}")
            return False
        else:
            return unit_label in [row["executor"] for row in rows]

    def _release_lock(self, executor: BaseExecutor, unit_label: str, unit_task: str) -> bool:
        """Releases a lock in the mysql.juju_units_operations table."""
        query = self._lock_query_builder.build_release_query(
            task=unit_task,
            instance=unit_label,
        )

        try:
            logger.debug(f"Attempting to release lock {unit_task} for unit {unit_label}")
            executor.execute_sql(query)
        except ExecutionError:
            logger.debug(f"Failed to release lock {unit_task}")
            return False
        else:
            return True

    def _get_cluster_member_addresses(self, exclude_units: list[str]) -> list[str]:
        """Get the addresses of the cluster's members."""
        topology = self.get_cluster_topology()
        if not topology:
            return []

        addresses = []
        for label, member in topology.items():
            if label not in exclude_units:
                address = member["address"].split(":")[0]
                addresses.append(address)

        return addresses

    def get_cluster_primary_address(self, from_instance: str | None = None) -> str | None:
        """Get the cluster primary's address."""
        if not from_instance:
            from_instance = self.instance_address

        client = MySQLClusterClient(
            executor=self._build_cluster_tcp_executor(from_instance),
        )

        try:
            logger.debug("Getting cluster primary address")
            status = client.fetch_cluster_status(self.cluster_name)
        except ExecutionError as e:
            raise MySQLGetClusterPrimaryAddressError() from e

        cluster_status = status["defaultReplicaSet"]["status"]
        cluster_address = status["defaultReplicaSet"]["primary"]

        if cluster_status == ClusterStatus.NO_QUORUM:
            raise MySQLGetClusterPrimaryAddressError()

        return cluster_address.split(":")[0]

    def get_cluster_global_primary_address(self, from_instance: str | None = None) -> str | None:
        """Get the cluster set global primary's address."""
        if not from_instance:
            from_instance = self.instance_address

        client = MySQLClusterClient(
            executor=self._build_cluster_tcp_executor(from_instance),
        )

        try:
            logger.debug("Getting cluster set primary address")
            status = client.fetch_cluster_set_status()
        except ExecutionError as e:
            raise MySQLGetClusterPrimaryAddressError() from e

        primary_cluster = status["primaryCluster"]
        primary_cluster_status = status["clusters"][primary_cluster]["globalStatus"]
        primary_cluster_address = status["clusters"][primary_cluster]["primary"]

        if primary_cluster_status == ClusterGlobalStatus.INVALIDATED:
            raise MySQLGetClusterPrimaryAddressError()

        return primary_cluster_address.split(":")[0]

    def get_cluster_topology(self) -> dict | None:
        """Get the cluster topology."""
        status = self.get_cluster_status()
        if not status:
            return None

        return status["defaultReplicaSet"]["topology"]

    def get_primary_label(self) -> str | None:
        """Get the label of the cluster's primary."""
        topology = self.get_cluster_topology()
        if not topology:
            return None

        for label, value in topology.items():
            if value["memberRole"] == InstanceRole.PRIMARY:
                return label

    def set_cluster_primary(self, new_primary_address: str) -> None:
        """Set the cluster primary."""
        try:
            self._cluster_client_tcp.promote_instance_within_cluster(
                cluster_name=self.cluster_name,
                instance_host=new_primary_address,
                instance_port=str(3306),
            )
        except ExecutionError as e:
            raise MySQLSetClusterPrimaryError() from e

    def get_mysql_version(self) -> str | None:
        """Get the running mysqld version."""
        try:
            version = self._instance_client_tcp.get_instance_version()
        except ExecutionError as e:
            raise MySQLGetMySQLVersionError() from e
        else:
            return version

    def update_user_password(self, username: str, new_password: str, host: str = "%") -> None:
        """Updates user password in MySQL database."""
        # Password is set on the global primary
        instance_address = self.get_cluster_global_primary_address()
        if not instance_address:
            raise MySQLCheckUserExistenceError("No primary found")

        client = MySQLInstanceClient(
            executor=self._build_instance_tcp_executor(instance_address),
            quoter=self._quoter,
        )

        user = User(username, host)

        try:
            client.update_instance_user(user, new_password)
        except ExecutionError as e:
            raise MySQLCheckUserExistenceError() from e

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_fixed(GET_MEMBER_ROLE_TIME),
    )
    def get_member_role(self) -> str:
        """Get member role in the cluster."""
        try:
            role = self._instance_client_tcp.get_instance_replication_role()
        except ExecutionError as e:
            raise MySQLUnableToGetMemberStateError() from e

        if not role:
            return "UNKNOWN"

        return role.value

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_fixed(GET_MEMBER_STATE_TIME),
    )
    def get_member_state(self) -> str:
        """Get member state in the cluster."""
        try:
            state = self._instance_client_tcp.get_instance_replication_state()
        except ExecutionError as e:
            raise MySQLUnableToGetMemberStateError() from e

        if not state:
            return "UNKNOWN"

        return state.value

    def is_cluster_auto_rejoin_ongoing(self) -> bool:
        """Check if the instance is performing a cluster auto rejoin operation."""
        return self._instance_client_tcp.check_work_ongoing("%auto-rejoin%")

    def is_cluster_replica(self, from_instance: str | None = None) -> bool | None:
        """Check if this cluster is a replica in a cluster set."""
        cluster_set_status = self.get_cluster_set_status(from_instance=from_instance, extended=0)
        if not cluster_set_status:
            return

        cluster_spec = cluster_set_status["clusters"].get(self.cluster_name)
        if not cluster_spec:
            return

        return cluster_spec["clusterRole"] == ClusterRole.REPLICA

    def get_cluster_set_name(self, from_instance: str | None = None) -> str | None:
        """Get cluster set name."""
        cluster_set_status = self.get_cluster_set_status(from_instance=from_instance, extended=0)
        if not cluster_set_status:
            return

        return cluster_set_status["domainName"]

    def stop_group_replication(self) -> None:
        """Stop Group replication if enabled on the instance."""
        with suppress(ExecutionError):
            self._instance_client_tcp.stop_instance_replication()

    def start_group_replication(self) -> None:
        """Start Group replication on the instance."""
        with suppress(ExecutionError):
            self._instance_client_tcp.start_instance_replication()

    def force_quorum_from_instance(self) -> None:
        """Force quorum from the current instance.

        Recovery for cases where majority loss put the cluster in defunct state.
        """
        # This is the ONLY operation in MySQL Shell 8.0 that requires
        # an explicit username + password in the instance definition string.
        # Otherwise, the `ubuntu` user is used.
        instance_def = (
            f"{self.cluster_admin_user}:{self.cluster_admin_password}@{self.instance_address}"
        )

        try:
            self._cluster_client_tcp.force_instance_quorum_into_cluster(
                cluster_name=self.cluster_name,
                instance_host=instance_def,
                instance_port=str(3306),
            )
        except ExecutionError as e:
            raise MySQLForceQuorumFromInstanceError() from e

    def reboot_from_complete_outage(self) -> None:
        """Wrapper for reboot_cluster_from_complete_outage command."""
        try:
            self._cluster_client_tcp.reboot_cluster(self.cluster_name)
        except ExecutionError as e:
            raise MySQLRebootFromCompleteOutageError() from e

    def hold_if_recovering(self) -> None:
        """Hold execution if member is recovering."""
        while True:
            try:
                member_state = self.get_member_state()
            except MySQLUnableToGetMemberStateError:
                break
            if member_state == InstanceState.RECOVERING:
                logger.debug("Unit is recovering")
                time.sleep(RECOVERY_CHECK_TIME)
            else:
                break

    def set_instance_offline_mode(self, offline_mode: bool = False) -> None:
        """Sets the instance offline_mode."""
        mode = "ON" if offline_mode else "OFF"

        try:
            self._instance_client_tcp.set_instance_variable(Scope.GLOBAL, "offline_mode", mode)
        except ExecutionError as e:
            raise MySQLSetInstanceOfflineModeError() from e

    def set_instance_option(self, option: str, value: Any) -> None:
        """Sets an instance option."""
        try:
            self._cluster_client_tcp.update_instance_within_cluster(
                cluster_name=self.cluster_name,
                instance_host=self.instance_address,
                instance_port=str(3306),
                options={option: value},
            )
        except ExecutionError as e:
            raise MySQLSetInstanceOptionError() from e

    def offline_mode_and_hidden_instance_exists(self) -> bool:
        """Indicates whether an instance exists in offline_mode and hidden from router."""
        try:
            cluster_topology = self.get_cluster_topology()
        except ExecutionError as e:
            raise MySQLOfflineModeAndHiddenInstanceExistsError() from e

        selectors = [
            lambda m: "Instance has offline_mode enabled" in m.get("instanceErrors", ""),
            lambda m: m.get("hiddenFromRouter"),
        ]

        for _, member in cluster_topology.items():
            if all(selector(member) for selector in selectors):
                return True

        return False

    def get_innodb_buffer_pool_parameters(
        self, available_memory: int
    ) -> tuple[int, int | None, int | None]:
        """Calculate innodb buffer pool parameters for the instance."""
        # Reference: based off xtradb-cluster-operator
        # https://github.com/percona/percona-xtradb-cluster-operator/blob/main/pkg/pxc/app/config/autotune.go#L31-L54

        chunk_size_min = BYTES_1MiB
        chunk_size_default = 128 * BYTES_1MiB
        group_replication_message_cache_default = BYTES_1GiB

        try:
            innodb_buffer_pool_chunk_size = None
            group_replication_message_cache = None

            pool_size = int(available_memory * 0.75) - group_replication_message_cache_default

            if pool_size < 0 or available_memory - pool_size < BYTES_1GB:
                group_replication_message_cache = 128 * BYTES_1MiB
                pool_size = int(available_memory * 0.5)

            if pool_size % chunk_size_default != 0:
                # round pool_size to be a multiple of chunk_size_default
                pool_size += chunk_size_default - (pool_size % chunk_size_default)

            if pool_size > BYTES_1GiB:
                chunk_size = int(pool_size / 8)

                if chunk_size % chunk_size_min != 0:
                    # round chunk_size to a multiple of chunk_size_min
                    chunk_size += chunk_size_min - (chunk_size % chunk_size_min)

                pool_size = chunk_size * 8

                innodb_buffer_pool_chunk_size = chunk_size

            return (
                pool_size,
                innodb_buffer_pool_chunk_size,
                group_replication_message_cache,
            )
        except Exception as e:
            logger.error("Failed to compute innodb buffer pool parameters")
            raise MySQLGetAutoTuningParametersError(
                "Error computing buffer pool parameters"
            ) from e

    def get_max_connections(self, available_memory: int) -> int:
        """Calculate max_connections parameter for the instance."""
        # Reference: based off xtradb-cluster-operator
        # https://github.com/percona/percona-xtradb-cluster-operator/blob/main/pkg/pxc/app/config/autotune.go#L61-L70

        bytes_per_connection = 12 * BYTES_1MiB

        if available_memory < bytes_per_connection:
            logger.error(f"Not enough memory for running MySQL: {available_memory=}")
            raise MySQLGetAutoTuningParametersError("Not enough memory for running MySQL")

        return available_memory // bytes_per_connection

    @abstractmethod
    def get_available_memory(self) -> int:
        """Platform dependent method to get the available memory for mysql-server."""
        raise NotImplementedError

    def execute_backup_commands(
        self,
        s3_path: str,
        s3_parameters: dict[str, str],
        xtrabackup_location: str,
        xbcloud_location: str,
        xtrabackup_plugin_dir: str,
        mysqld_socket_file: str,
        tmp_base_directory: str,
        defaults_config_file: str,
        user: str | None = None,
        group: str | None = None,
    ) -> tuple[str, str]:
        """Executes commands to create a backup with the given args."""
        nproc_command = ["nproc"]
        make_temp_dir_command = f"mktemp --directory {tmp_base_directory}/xtra_backup_XXXX".split()

        try:
            nproc, _ = self._execute_commands(nproc_command)
            tmp_dir, _ = self._execute_commands(make_temp_dir_command, user=user, group=group)
        except MySQLExecError as e:
            logger.error("Failed to execute commands prior to running backup")
            raise MySQLExecuteBackupCommandsError from e
        except Exception as e:
            # Catch all other exceptions to prevent the database being stuck in
            # a bad state due to pre-backup operations
            logger.error("Failed unexpectedly to execute commands prior to running backup")
            raise MySQLExecuteBackupCommandsError from e

        # TODO: remove flags --no-server-version-check
        # when MySQL and XtraBackup versions are in sync
        xtrabackup_commands = [
            f"{xtrabackup_location} --defaults-file={defaults_config_file}",
            "--defaults-group=mysqld",
            "--no-version-check",
            f"--parallel={nproc}",
            f"--user={self.backups_user}",
            f"--password={self.backups_password}",
            f"--socket={mysqld_socket_file}",
            "--lock-ddl",
            "--backup",
            "--stream=xbstream",
            f"--xtrabackup-plugin-dir={xtrabackup_plugin_dir}",
            f"--target-dir={tmp_dir}",
            "--no-server-version-check",
            f"| {xbcloud_location} put",
            "--curl-retriable-errors=7",
            "--insecure",
            "--parallel=10",
            "--md5",
            "--storage=S3",
            f"--s3-region={s3_parameters['region']}",
            f"--s3-bucket={s3_parameters['bucket']}",
            f"--s3-endpoint={s3_parameters['endpoint']}",
            f"--s3-api-version={s3_parameters['s3-api-version']}",
            f"--s3-bucket-lookup={s3_parameters['s3-uri-style']}",
            f"{s3_path}",
        ]

        try:
            logger.debug(
                f"Command to create backup: {' '.join(xtrabackup_commands).replace(self.backups_password, 'xxxxxxxxxxxx')}"
            )

            # ACCESS_KEY_ID and SECRET_ACCESS_KEY envs auto picked by xbcloud
            return self._execute_commands(
                xtrabackup_commands,
                bash=True,
                user=user,
                group=group,
                env_extra={
                    "ACCESS_KEY_ID": s3_parameters["access-key"],
                    "SECRET_ACCESS_KEY": s3_parameters["secret-key"],
                },
                stream_output="stderr",
            )
        except MySQLExecError as e:
            logger.error("Failed to execute backup commands")
            raise MySQLExecuteBackupCommandsError from e
        except Exception as e:
            # Catch all other exceptions to prevent the database being stuck in
            # a bad state due to pre-backup operations
            logger.error("Failed unexpectedly to execute backup commands")
            raise MySQLExecuteBackupCommandsError from e

    def delete_temp_backup_directory(
        self,
        tmp_base_directory: str,
        user: str | None = None,
        group: str | None = None,
    ) -> None:
        """Delete the temp backup directory."""
        delete_temp_dir_command = f"find {tmp_base_directory} -wholename {tmp_base_directory}/xtra_backup_* -delete".split()

        try:
            logger.debug(
                f"Command to delete temp backup directory: {' '.join(delete_temp_dir_command)}"
            )

            self._execute_commands(
                delete_temp_dir_command,
                user=user,
                group=group,
            )
        except MySQLExecError as e:
            logger.error("Failed to delete temp backup directory")
            raise MySQLDeleteTempBackupDirectoryError(e.message) from e
        except Exception as e:
            logger.error("Failed to delete temp backup directory")
            raise MySQLDeleteTempBackupDirectoryError from e

    def retrieve_backup_with_xbcloud(
        self,
        backup_id: str,
        s3_parameters: dict[str, str],
        temp_restore_directory: str,
        xbcloud_location: str,
        xbstream_location: str,
        user: str | None = None,
        group: str | None = None,
    ) -> tuple[str, str, str]:
        """Retrieve the specified backup from S3."""
        nproc_command = ["nproc"]
        make_temp_dir_command = (
            f"mktemp --directory {temp_restore_directory}/#mysql_sst_XXXX".split()
        )

        try:
            nproc, _ = self._execute_commands(nproc_command)

            tmp_dir, _ = self._execute_commands(
                make_temp_dir_command,
                user=user,
                group=group,
            )
        except MySQLExecError as e:
            logger.error("Failed to execute commands prior to running xbcloud get")
            raise MySQLRetrieveBackupWithXBCloudError(e.message) from e

        retrieve_backup_command = [
            f"{xbcloud_location} get",
            "--curl-retriable-errors=7",
            "--parallel=10",
            "--storage=S3",
            f"--s3-region={s3_parameters['region']}",
            f"--s3-bucket={s3_parameters['bucket']}",
            f"--s3-endpoint={s3_parameters['endpoint']}",
            f"--s3-bucket-lookup={s3_parameters['s3-uri-style']}",
            f"--s3-api-version={s3_parameters['s3-api-version']}",
            f"{s3_parameters['path']}/{backup_id}",
            f"| {xbstream_location}",
            "--decompress",
            "-x",
            f"-C {tmp_dir}",
            f"--parallel={nproc}",
        ]

        try:
            logger.debug(f"Command to retrieve backup: {' '.join(retrieve_backup_command)}")

            # ACCESS_KEY_ID and SECRET_ACCESS_KEY envs auto picked by xbcloud
            stdout, stderr = self._execute_commands(
                retrieve_backup_command,
                bash=True,
                env_extra={
                    "ACCESS_KEY_ID": s3_parameters["access-key"],
                    "SECRET_ACCESS_KEY": s3_parameters["secret-key"],
                },
                user=user,
                group=group,
                stream_output="stderr",
            )
            return (stdout, stderr, tmp_dir)
        except MySQLExecError as e:
            logger.error("Failed to retrieve backup")
            raise MySQLRetrieveBackupWithXBCloudError(e.message) from e
        except Exception as e:
            logger.error("Failed to retrieve backup")
            raise MySQLRetrieveBackupWithXBCloudError from e

    def prepare_backup_for_restore(
        self,
        backup_location: str,
        xtrabackup_location: str,
        xtrabackup_plugin_dir: str,
        user: str | None = None,
        group: str | None = None,
    ) -> tuple[str, str]:
        """Prepare the backup in the provided dir for restore."""
        try:
            innodb_buffer_pool_size, _, _ = self.get_innodb_buffer_pool_parameters(
                self.get_available_memory()
            )
        except MySQLGetAutoTuningParametersError as e:
            raise MySQLPrepareBackupForRestoreError(e.message) from e

        prepare_backup_command = [
            xtrabackup_location,
            "--prepare",
            f"--use-memory={innodb_buffer_pool_size}",
            "--no-version-check",
            "--rollback-prepared-trx",
            f"--xtrabackup-plugin-dir={xtrabackup_plugin_dir}",
            f"--target-dir={backup_location}",
        ]

        try:
            logger.debug(
                f"Command to prepare backup for restore: {' '.join(prepare_backup_command)}"
            )

            return self._execute_commands(
                prepare_backup_command,
                user=user,
                group=group,
            )
        except MySQLExecError as e:
            logger.error("Failed to prepare backup for restore")
            raise MySQLPrepareBackupForRestoreError(e.message) from e
        except Exception as e:
            logger.error("Failed to prepare backup for restore")
            raise MySQLPrepareBackupForRestoreError from e

    def empty_data_files(
        self,
        mysql_data_directory: str,
        user: str | None = None,
        group: str | None = None,
    ) -> None:
        """Empty the mysql data directory in preparation of backup restore."""
        empty_data_files_command = [
            "find",
            mysql_data_directory,
            "-not",
            "-path",
            f"{mysql_data_directory}/#mysql_sst_*",
            "-not",
            "-path",
            mysql_data_directory,
            "-delete",
        ]

        try:
            logger.debug(f"Command to empty data directory: {' '.join(empty_data_files_command)}")
            self._execute_commands(
                empty_data_files_command,
                user=user,
                group=group,
            )
        except MySQLExecError as e:
            logger.error("Failed to empty data directory in prep for backup restore")
            raise MySQLEmptyDataDirectoryError(e.message) from e
        except Exception as e:
            logger.error("Failed to empty data directory in prep for backup restore")
            raise MySQLEmptyDataDirectoryError from e

    def restore_backup(
        self,
        backup_location: str,
        xtrabackup_location: str,
        defaults_config_file: str,
        mysql_data_directory: str,
        xtrabackup_plugin_directory: str,
        user: str | None = None,
        group: str | None = None,
    ) -> tuple[str, str]:
        """Restore the provided prepared backup."""
        restore_backup_command = [
            xtrabackup_location,
            f"--defaults-file={defaults_config_file}",
            "--defaults-group=mysqld",
            f"--datadir={mysql_data_directory}",
            "--no-version-check",
            "--move-back",
            "--force-non-empty-directories",
            f"--xtrabackup-plugin-dir={xtrabackup_plugin_directory}",
            f"--target-dir={backup_location}",
        ]

        try:
            logger.debug(f"Command to restore backup: {' '.join(restore_backup_command)}")

            return self._execute_commands(
                restore_backup_command,
                user=user,
                group=group,
            )
        except MySQLExecError as e:
            logger.error("Failed to restore backup")
            raise MySQLRestoreBackupError(e.message) from e
        except Exception as e:
            logger.error("Failed to restore backup")
            raise MySQLRestoreBackupError from e

    def restore_pitr(
        self,
        host: str,
        mysql_user: str,
        password: str,
        s3_parameters: dict[str, str],
        restore_to_time: str,
        user: str | None = None,
        group: str | None = None,
    ) -> tuple[str, str]:
        """Run point-in-time-recovery using binary logs from the S3 repository.

        Args:
            host: the MySQL host to connect to.
            mysql_user: the MySQL user to connect to.
            password: the password of the provided MySQL user.
            s3_parameters: S3 relation parameters.
            restore_to_time: the MySQL timestamp to restore to or keyword `latest`.
            user: the user with which to execute the commands.
            group: the group with which to execute the commands.
        """
        binlogs_path = s3_parameters["path"].rstrip("/")
        bucket_url = f"{s3_parameters['bucket']}/{binlogs_path}/binlogs"

        try:
            return self._execute_commands(
                [
                    CHARMED_MYSQL_PITR_HELPER,
                    "recover",
                ],
                user=user,
                group=group,
                env_extra={
                    "BINLOG_S3_ENDPOINT": s3_parameters["endpoint"],
                    "HOST": host,
                    "USER": mysql_user,
                    "PASS": password,
                    "PITR_DATE": restore_to_time if restore_to_time != "latest" else "",
                    "PITR_RECOVERY_TYPE": "latest" if restore_to_time == "latest" else "date",
                    "STORAGE_TYPE": "s3",
                    "BINLOG_ACCESS_KEY_ID": s3_parameters["access-key"],
                    "BINLOG_SECRET_ACCESS_KEY": s3_parameters["secret-key"],
                    "BINLOG_S3_REGION": s3_parameters["region"],
                    "BINLOG_S3_BUCKET_URL": bucket_url,
                },
            )
        except MySQLExecError as e:
            logger.exception("Failed to restore pitr")
            raise MySQLRestorePitrError(e.message) from e
        except Exception as e:
            logger.exception("Failed to restore pitr")
            raise MySQLRestorePitrError from e

    def delete_temp_restore_directory(
        self,
        temp_restore_directory: str,
        user: str | None = None,
        group: str | None = None,
    ) -> None:
        """Delete the temp restore directory from the mysql data directory."""
        logger.info(f"Deleting temp restore directory in {temp_restore_directory}")
        delete_temp_restore_directory_command = [
            "find",
            temp_restore_directory,
            "-wholename",
            f"{temp_restore_directory}/#mysql_sst_*",
            "-delete",
        ]

        try:
            logger.debug(
                f"Command to delete temp restore directory: {' '.join(delete_temp_restore_directory_command)}"
            )
            self._execute_commands(
                delete_temp_restore_directory_command,
                user=user,
                group=group,
            )
        except MySQLExecError as e:
            logger.error("Failed to remove temp backup directory")
            raise MySQLDeleteTempRestoreDirectoryError(e.message) from e

    @abstractmethod
    def _execute_commands(
        self,
        commands: list[str],
        bash: bool = False,
        user: str | None = None,
        group: str | None = None,
        env_extra: dict | None = None,
        stream_output: str | None = None,
    ) -> tuple[str, str]:
        """Execute commands on the server where MySQL is running."""
        raise NotImplementedError

    def tls_setup(
        self,
        ca_path: str = "ca.pem",
        key_path: str = "server-key.pem",
        cert_path: str = "server-cert.pem",
        require_tls: bool = False,
    ) -> None:
        """Setup TLS files and requirement mode."""
        tls_var = "require_secure_transport"
        tls_val = "ON" if require_tls else "OFF"

        try:
            self._instance_client_tcp.set_instance_variable(Scope.PERSIST, "ssl_ca", ca_path)
            self._instance_client_tcp.set_instance_variable(Scope.PERSIST, "ssl_key", key_path)
            self._instance_client_tcp.set_instance_variable(Scope.PERSIST, "ssl_cert", cert_path)
            self._instance_client_tcp.set_instance_variable(Scope.PERSIST, tls_var, tls_val)
            self._instance_client_tcp.reload_instance_certs()
        except ExecutionError as e:
            raise MySQLTLSSetupError() from e

    def kill_client_sessions(self) -> None:
        """Kill all open client session connections."""
        try:
            self._instance_client_tcp.stop_instance_processes(
                self._instance_client_tcp.search_instance_connection_processes("%"),
            )
        except ExecutionError as e:
            raise MySQLKillSessionError() from e

    def check_mysqlsh_connection(self) -> bool:
        """Checks if it is possible to connect to the server with mysqlsh."""
        executor = self._build_instance_sock_executor()

        try:
            executor.check_connection()
            return True
        except ExecutionError:
            logger.error("Failed to connect to MySQL via socket")
            return False

    def get_pid_of_port_3306(self) -> str | None:
        """Retrieves the PID of the process that is bound to port 3306."""
        get_pid_command = ["fuser", "3306/tcp"]

        try:
            stdout, _ = self._execute_commands(get_pid_command)
            return stdout
        except MySQLExecError:
            return None

    def flush_mysql_logs(self, log_types: LogType | list[LogType]) -> None:
        """Flushes the specified logs_type logs."""
        if not isinstance(log_types, list):
            log_types = [log_types]

        query = self._log_query_builder.build_logs_flushing_query(log_types)
        executor = self._build_instance_tcp_executor(self.instance_address)

        with suppress(ExecutionError):
            executor.execute_sql(query)

    def flush_mysql_audit_log(self) -> None:
        """Flushes the audit log type."""
        with suppress(ExecutionError):
            self._instance_client_tcp.set_instance_variable(Scope.GLOBAL, "audit_log_flush", "ON")

    def get_non_system_databases(self) -> set[str]:
        """Return a set with all non system databases on the server."""
        server_databases = self._instance_client_tcp.search_instance_databases("%")
        return set(server_databases) - {
            "information_schema",
            "mysql",
            "mysql_innodb_cluster_metadata",
            "performance_schema",
            "sys",
        }

    def strip_off_passwords(self, input_string: str | None) -> str:
        """Strips off passwords from the input string."""
        if not input_string:
            return ""
        stripped_input = input_string
        # Not an actual pass
        hidden_pass = "*****"  # noqa: S105
        for password in self.passwords:
            stripped_input = stripped_input.replace(password, hidden_pass)
        if "IDENTIFIED" in input_string:
            # when failure occurs for password setting (user creation, password rotation)
            pattern = r"(?<=IDENTIFIED BY\ \')[^\']+(?=\')"
            stripped_input = re.sub(pattern, hidden_pass, stripped_input)
        return stripped_input

    def get_current_group_replication_id(self) -> str:
        """Get the current group replication id."""
        try:
            group_id = self._instance_client_tcp.get_instance_variable(
                scope=Scope.GLOBAL,
                name="group_replication_group_name",
            )
        except ExecutionError as e:
            raise MySQLGetGroupReplicationIDError() from e
        else:
            return group_id

    @abstractmethod
    def _file_exists(self, path: str) -> bool:
        """Check if a file exists."""
        raise NotImplementedError

    @abstractmethod
    def is_mysqld_running(self) -> bool:
        """Returns whether mysqld is running."""
        raise NotImplementedError

    @abstractmethod
    def is_server_connectable(self) -> bool:
        """Returns whether the server is connectable."""
        raise NotImplementedError

    @abstractmethod
    def stop_mysqld(self) -> None:
        """Stops the mysqld process."""
        raise NotImplementedError

    @abstractmethod
    def start_mysqld(self) -> None:
        """Starts the mysqld process."""
        raise NotImplementedError

    @abstractmethod
    def restart_mysql_exporter(self) -> None:
        """Restart the mysqld exporter."""
        raise NotImplementedError

    @abstractmethod
    def wait_until_mysql_connection(self, check_port: bool = True) -> None:
        """Wait until a connection to MySQL has been obtained.

        Implemented in subclasses, test for socket file existence.
        """
        raise NotImplementedError

    @abstractmethod
    def reset_data_dir(self) -> None:
        """Reset the data directory."""
        raise NotImplementedError

    @abstractmethod
    def reconcile_binlogs_collection(
        self, force_restart: bool = False, ignore_inactive_error: bool = False
    ) -> bool:
        """Start or stop binlogs collecting service.

        Based on the `binlogs-collecting` app peer data value and unit leadership.

        Args:
            force_restart: whether to restart service even if it's already running.
            ignore_inactive_error: whether to not log an error when the service should be enabled but not active right now.

        Returns: whether the operation was successful.
        """
        raise NotImplementedError

    @abstractmethod
    def get_cluster_members(self) -> list[str]:
        """Get cluster members in MySQL MEMBER_HOST format.

        Returns: list of the cluster members in the MySQL MEMBER_HOST format.
        """
        raise NotImplementedError
