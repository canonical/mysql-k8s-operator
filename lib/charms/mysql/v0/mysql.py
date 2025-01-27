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

    # abstract method implementation
    @retry(reraise=True, stop=stop_after_delay(30), wait=wait_fixed(5))
    def wait_until_mysql_connection(self) -> None:
        if not os.path.exists(MYSQLD_SOCK_FILE):
            raise MySQLServiceNotRunningError()

    ...
```

The module also provides a set of custom exceptions, used to trigger specific
error handling on the subclass and in the charm code.


"""

import configparser
import dataclasses
import enum
import hashlib
import io
import json
import logging
import os
import re
import socket
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    Union,
    get_args,
)

import ops
from charms.data_platform_libs.v0.data_interfaces import DataPeerData, DataPeerUnitData
from ops.charm import ActionEvent, CharmBase, RelationBrokenEvent
from ops.model import Unit
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
    wait_random,
)

from constants import (
    BACKUPS_PASSWORD_KEY,
    BACKUPS_USERNAME,
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
from utils import generate_random_password

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from charms.mysql.v0.async_replication import MySQLAsyncReplicationOffer

# The unique Charmhub library identifier, never change it
LIBID = "8c1428f06b1b4ec8bf98b7d980a38a8c"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

LIBPATCH = 81

UNIT_TEARDOWN_LOCKNAME = "unit-teardown"
UNIT_ADD_LOCKNAME = "unit-add"

BYTES_1GiB = 1073741824  # 1 gibibyte
BYTES_1GB = 1000000000  # 1 gigabyte
BYTES_1MB = 1000000  # 1 megabyte
BYTES_1MiB = 1048576  # 1 mebibyte
RECOVERY_CHECK_TIME = 10  # seconds
GET_MEMBER_STATE_TIME = 10  # seconds
MAX_CONNECTIONS_FLOOR = 10
MIM_MEM_BUFFERS = 200 * BYTES_1MiB
ADMIN_PORT = 33062

SECRET_INTERNAL_LABEL = "secret-id"
SECRET_DELETED_LABEL = "None"

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
        return "<{}.{} {}>".format(type(self).__module__, type(self).__name__, self.args)

    @property
    def name(self):
        """Return a string representation of the model plus class."""
        return "<{}.{}>".format(type(self).__module__, type(self).__name__)


class MySQLConfigureMySQLUsersError(Error):
    """Exception raised when creating a user fails."""


class MySQLCheckUserExistenceError(Error):
    """Exception raised when checking for the existence of a MySQL user."""


class MySQLConfigureRouterUserError(Error):
    """Exception raised when configuring the MySQLRouter user."""


class MySQLCreateApplicationDatabaseAndScopedUserError(Error):
    """Exception raised when creating application database and scoped user."""


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


class MySQLRemoveInstanceRetryError(Error):
    """Exception raised when there is an issue removing an instance.

    Utilized by tenacity to retry the method.
    """


class MySQLRemoveInstanceError(Error):
    """Exception raised when there is an issue removing an instance.

    Exempt from the retry mechanism provided by tenacity.
    """


class MySQLInitializeJujuOperationsTableError(Error):
    """Exception raised when there is an issue initializing the juju units operations table."""


class MySQLClientError(Error):
    """Exception raised when there is an issue using the mysql cli or mysqlsh.

    Abstract platform specific exceptions for external commands execution Errors.
    """


class MySQLGetClusterMembersAddressesError(Error):
    """Exception raised when there is an issue getting the cluster members addresses."""


class MySQLGetMySQLVersionError(Error):
    """Exception raised when there is an issue getting the MySQL version."""


class MySQLGetClusterPrimaryAddressError(Error):
    """Exception raised when there is an issue getting the primary instance."""


class MySQLSetClusterPrimaryError(Error):
    """Exception raised when there is an issue setting the primary instance."""


class MySQLGrantPrivilegesToUserError(Error):
    """Exception raised when there is an issue granting privileges to user."""


class MySQLNoMemberStateError(Error):
    """Exception raised when there is no member state."""


class MySQLUnableToGetMemberStateError(Error):
    """Exception raised when unable to get member state."""


class MySQLGetClusterEndpointsError(Error):
    """Exception raised when there is an issue getting cluster endpoints."""


class MySQLRebootFromCompleteOutageError(Error):
    """Exception raised when there is an issue rebooting from complete outage."""


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


class MySQLGetVariableError(Error):
    """Exception raised when there is an issue getting a variable."""


class MySQLServerNotUpgradableError(Error):
    """Exception raised when there is an issue checking for upgradeability."""


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


class MySQLFencingWritesError(Error):
    """Exception raised when there is an issue fencing or unfencing writes."""


class MySQLRejoinClusterError(Error):
    """Exception raised when there is an issue trying to rejoin a cluster to the cluster set."""


class MySQLPluginInstallError(Error):
    """Exception raised when there is an issue installing a MySQL plugin."""


@dataclasses.dataclass
class RouterUser:
    """MySQL Router user."""

    username: str
    router_id: str


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
        self.framework.observe(self.on.recreate_cluster_action, self._recreate_cluster)

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
    def get_unit_address(self, unit: Unit) -> str:
        """Return unit address."""
        # each platform has its own way to get an arbitrary unit address
        raise NotImplementedError

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
        if event.params.get("cluster-set"):
            logger.debug("Getting cluster set status")
            status = self._mysql.get_cluster_set_status(extended=0)
        else:
            logger.debug("Getting cluster status")
            status = self._mysql.get_cluster_status()

        if status:
            event.set_results({
                "success": True,
                "status": status,
            })
        else:
            event.set_results({
                "success": False,
                "message": "Failed to read cluster status.  See logs for more information.",
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

        state, role = self._mysql.get_member_state()

        self.unit_peer_data.update({"member-state": state, "member-role": role})

    @property
    def peers(self) -> Optional[ops.model.Relation]:
        """Retrieve the peer relation."""
        return self.model.get_relation(PEER)

    @property
    def cluster_initialized(self) -> bool:
        """Returns True if the cluster is initialized."""
        if not self.app_peer_data.get("cluster-name"):
            return False

        for unit in self.app_units:
            if self._mysql.cluster_metadata_exists(self.get_unit_address(unit)):
                return True

        return False

    @property
    def only_one_cluster_node_thats_uninitialized(self) -> Optional[bool]:
        """Check if only a single cluster node exists across all units."""
        if not self.app_peer_data.get("cluster-name"):
            return None

        total_cluster_nodes = 0
        for unit in self.app_units:
            total_cluster_nodes += self._mysql.get_cluster_node_count(
                from_instance=self.get_unit_address(unit)
            )

        total_online_cluster_nodes = 0
        for unit in self.app_units:
            total_online_cluster_nodes += self._mysql.get_cluster_node_count(
                from_instance=self.get_unit_address(unit), node_status=MySQLMemberState["ONLINE"]
            )

        return total_cluster_nodes == 1 and total_online_cluster_nodes == 0

    @property
    def cluster_fully_initialized(self) -> bool:
        """Returns True if the cluster is fully initialized.

        Fully initialized means that all unit that can be joined are joined.
        """
        return self._mysql.get_cluster_node_count(node_status=MySQLMemberState["ONLINE"]) == min(
            GR_MAX_MEMBERS, self.app.planned_units()
        )

    @property
    def unit_configured(self) -> bool:
        """Check if the unit is configured to be part of the cluster."""
        return self._mysql.is_instance_configured_for_innodb(
            self.get_unit_address(self.unit), self.unit_label
        )

    @property
    def unit_initialized(self) -> bool:
        """Check if the unit is added to the cluster."""
        return self._mysql.cluster_metadata_exists(self.get_unit_address(self.unit))

    @property
    def app_peer_data(self) -> Union[ops.RelationDataContent, dict]:
        """Application peer relation data object."""
        if self.peers is None:
            return {}

        return self.peers.data[self.app]

    @property
    def unit_peer_data(self) -> Union[ops.RelationDataContent, dict]:
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
        return self.unit.name.replace("/", "-")

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
                lambda relation: not (
                    isinstance(self.current_event, RelationBrokenEvent)
                    and self.current_event.relation.id == relation.id
                ),
                cos_relations,
            )
        )

        return len(active_cos_relations) > 0

    @property
    def active_status_message(self) -> str:
        """Active status message."""
        if self.unit_peer_data.get("member-role") == "primary":
            if self._mysql.is_cluster_replica():
                status = self._mysql.get_replica_cluster_status()
                if status == "ok":
                    return "Standby"
                else:
                    return f"Standby ({status})"
            elif self._mysql.is_cluster_writes_fenced():
                return "Primary (fenced writes)"
            else:
                return "Primary"

        return ""

    @property
    def removing_unit(self) -> bool:
        """Check if the unit is being removed."""
        return self.unit_peer_data.get("unit-status") == "removing"

    def peer_relation_data(self, scope: Scopes) -> DataPeerData:
        """Returns the peer relation data per scope."""
        if scope == APP_SCOPE:
            return self.peer_relation_app
        elif scope == UNIT_SCOPE:
            return self.peer_relation_unit

    def get_secret(
        self,
        scope: Scopes,
        key: str,
    ) -> Optional[str]:
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
        if not (value := self.peer_relation_data(scope).fetch_my_relation_field(peers.id, key)):
            if key in SECRET_KEY_FALLBACKS:
                value = self.peer_relation_data(scope).fetch_my_relation_field(
                    peers.id, SECRET_KEY_FALLBACKS[key]
                )
        return value

    def set_secret(self, scope: Scopes, key: str, value: Optional[str]) -> None:
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
        return hashlib.md5(random_characters.encode("utf-8")).hexdigest()


class MySQLMemberState(str, enum.Enum):
    """MySQL Cluster member state."""

    # TODO: python 3.11 has new enum.StrEnum
    #       that can remove str inheritance

    ONLINE = "online"
    RECOVERING = "recovering"
    OFFLINE = "offline"
    ERROR = "error"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"


class MySQLClusterState(str, enum.Enum):
    """MySQL Cluster state."""

    OK = "ok"
    FENCED = "fenced_writes"


class MySQLTextLogs(str, enum.Enum):
    """MySQL Text logs."""

    # TODO: python 3.11 has new enum.StrEnum
    #       that can remove str inheritance

    ERROR = "ERROR LOGS"
    GENERAL = "GENERAL LOGS"
    SLOW = "SLOW LOGS"
    AUDIT = "AUDIT LOGS"


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
    ):
        """Initialize the MySQL class."""
        self.instance_address = instance_address
        self.socket_uri = f"({socket_path})"
        self.cluster_name = cluster_name
        self.cluster_set_name = cluster_set_name
        self.root_password = root_password
        self.server_config_user = server_config_user
        self.server_config_password = server_config_password
        self.cluster_admin_user = cluster_admin_user
        self.cluster_admin_password = cluster_admin_password
        self.monitoring_user = monitoring_user
        self.monitoring_password = monitoring_password
        self.backups_user = backups_user
        self.backups_password = backups_password
        self.passwords = [
            self.root_password,
            self.server_config_password,
            self.cluster_admin_password,
            self.monitoring_password,
            self.backups_password,
        ]

    def instance_def(self, user: str, host: Optional[str] = None) -> str:
        """Return instance definition used on mysqlsh.

        Args:
            user: User name.
            host: Host name, default to unit address.
        """
        if host and ":" in host:
            # strip port from address
            host = host.split(":")[0]

        if user in (self.server_config_user, self.backups_user):
            # critical operator users use admin address
            return f"{host or self.instance_address}:{ADMIN_PORT}"
        elif host != self.instance_address:
            return f"{host}:3306"
        return f"{self.socket_uri}"

    def render_mysqld_configuration(  # noqa: C901
        self,
        *,
        profile: str,
        audit_log_enabled: bool,
        audit_log_strategy: str,
        memory_limit: Optional[int] = None,
        experimental_max_connections: Optional[int] = None,
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
            "bind-address": "0.0.0.0",
            "mysqlx-bind-address": "0.0.0.0",
            "admin_address": self.instance_address,
            "report_host": self.instance_address,
            "max_connections": str(max_connections),
            "innodb_buffer_pool_size": str(innodb_buffer_pool_size),
            "log_error_services": "log_filter_internal;log_sink_internal",
            "log_error": f"{snap_common}/var/log/mysql/error.log",
            "general_log": "OFF",
            "general_log_file": f"{snap_common}/var/log/mysql/general.log",
            "slow_query_log_file": f"{snap_common}/var/log/mysql/slow.log",
            "binlog_expire_logs_seconds": f"{binlog_retention_seconds}",
            "loose-audit_log_filter": "OFF",
            "loose-audit_log_policy": "LOGINS",
            "loose-audit_log_file": f"{snap_common}/var/log/mysql/audit.log",
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

    def configure_mysql_users(self, password_needed: bool = True) -> None:
        """Configure the MySQL users for the instance."""
        # SYSTEM_USER and SUPER privileges to revoke from the root users
        # Reference: https://dev.mysql.com/doc/refman/8.0/en/privileges-provided.html#priv_super
        privileges_to_revoke = (
            "SYSTEM_USER",
            "SYSTEM_VARIABLES_ADMIN",
            "SUPER",
            "REPLICATION_SLAVE_ADMIN",
            "GROUP_REPLICATION_ADMIN",
            "BINLOG_ADMIN",
            "SET_USER_ID",
            "ENCRYPTION_KEY_ADMIN",
            "VERSION_TOKEN_ADMIN",
            "CONNECTION_ADMIN",
        )

        # privileges for the backups user:
        #   https://docs.percona.com/percona-xtrabackup/8.0/using_xtrabackup/privileges.html#permissions-and-privileges-needed
        # CONNECTION_ADMIN added to provide it privileges to connect to offline_mode node
        configure_users_commands = (
            f"CREATE USER '{self.server_config_user}'@'%' IDENTIFIED BY '{self.server_config_password}'",
            f"GRANT ALL ON *.* TO '{self.server_config_user}'@'%' WITH GRANT OPTION",
            f"CREATE USER '{self.monitoring_user}'@'%' IDENTIFIED BY '{self.monitoring_password}' WITH MAX_USER_CONNECTIONS 3",
            f"GRANT SYSTEM_USER, SELECT, PROCESS, SUPER, REPLICATION CLIENT, RELOAD ON *.* TO '{self.monitoring_user}'@'%'",
            f"CREATE USER '{self.backups_user}'@'%' IDENTIFIED BY '{self.backups_password}'",
            f"GRANT CONNECTION_ADMIN, BACKUP_ADMIN, PROCESS, RELOAD, LOCK TABLES, REPLICATION CLIENT ON *.* TO '{self.backups_user}'@'%'",
            f"GRANT SELECT ON performance_schema.log_status TO '{self.backups_user}'@'%'",
            f"GRANT SELECT ON performance_schema.keyring_component_status TO '{self.backups_user}'@'%'",
            f"GRANT SELECT ON performance_schema.replication_group_members TO '{self.backups_user}'@'%'",
            "UPDATE mysql.user SET authentication_string=null WHERE User='root' and Host='localhost'",
            f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{self.root_password}'",
            f"REVOKE {', '.join(privileges_to_revoke)} ON *.* FROM 'root'@'localhost'",
            "FLUSH PRIVILEGES",
        )

        try:
            logger.debug(f"Configuring MySQL users for {self.instance_address}")
            if password_needed:
                self._run_mysqlcli_script(
                    configure_users_commands,
                    password=self.root_password,
                )
            else:
                self._run_mysqlcli_script(configure_users_commands)
        except MySQLClientError:
            logger.error(f"Failed to configure users for: {self.instance_address}")
            raise MySQLConfigureMySQLUsersError

    def _plugin_file_exists(self, plugin_file_name: str) -> bool:
        """Check if the plugin file exists.

        Args:
            plugin_file_name: Plugin file name, with the extension.

        """
        path = self.get_variable_value("plugin_dir")
        return self._file_exists(f"{path}/{plugin_file_name}")

    def install_plugins(self, plugins: list[str]) -> None:
        """Install extra plugins."""
        supported_plugins = {
            "audit_log": ("INSTALL PLUGIN audit_log SONAME", "audit_log.so"),
            "audit_log_filter": ("INSTALL PLUGIN audit_log_filter SONAME", "audit_log_filter.so"),
        }

        try:
            super_read_only = self.get_variable_value("super_read_only").lower() == "on"
            installed_plugins = self._get_installed_plugins()
            # disable super_read_only to install plugins
            for plugin in plugins:
                if plugin in installed_plugins:
                    # skip if the plugin is already installed
                    logger.info(f"{plugin=} already installed")
                    continue
                if plugin not in supported_plugins:
                    logger.warning(f"{plugin=} is not supported")
                    continue

                command_prefix, plugin_file = (
                    supported_plugins[plugin][0],
                    supported_plugins[plugin][1],
                )

                if not self._plugin_file_exists(plugin_file):
                    logger.warning(f"{plugin=} file not found. Skip installation")
                    continue

                command = f"{command_prefix} '{plugin_file}';"
                if super_read_only:
                    command = (
                        "SET GLOBAL super_read_only=OFF",
                        command,
                        "SET GLOBAL super_read_only=ON",
                    )
                else:
                    command = (command,)
                logger.info(f"Installing {plugin=}")
                self._run_mysqlcli_script(
                    command,
                    user=self.server_config_user,
                    password=self.server_config_password,
                )
        except MySQLClientError:
            logger.error(f"Failed to install {plugin=}")  # type: ignore
            raise MySQLPluginInstallError
        except MySQLGetVariableError:
            # workaround for config changed triggered after failed upgrade
            # the check fails for charms revisions not using admin address
            logger.warning("Failed to get super_read_only variable. Skip plugin installation")

    def uninstall_plugins(self, plugins: list[str]) -> None:
        """Uninstall plugins."""
        super_read_only = self.get_variable_value("super_read_only").lower() == "on"
        try:
            installed_plugins = self._get_installed_plugins()
            # disable super_read_only to uninstall plugins
            for plugin in plugins:
                if plugin not in installed_plugins:
                    # skip if the plugin is not installed
                    continue
                logger.debug(f"Uninstalling plugin {plugin}")

                command = f"UNINSTALL PLUGIN {plugin};"
                if super_read_only:
                    command = (
                        "SET GLOBAL super_read_only=OFF",
                        command,
                        "SET GLOBAL super_read_only=ON",
                    )
                else:
                    command = (command,)
                self._run_mysqlcli_script(
                    command,
                    user=self.server_config_user,
                    password=self.server_config_password,
                )
        except MySQLClientError:
            logger.error(
                f"Failed to uninstall {plugin=}",  # type: ignore
            )
            raise MySQLPluginInstallError

    def _get_installed_plugins(self) -> set[str]:
        """Return a set of explicitly installed plugins."""
        try:
            output = self._run_mysqlcli_script(
                ("select name from mysql.plugin",),
                password=self.root_password,
            )
            return {
                plugin[0] for plugin in output if plugin[0] not in ["clone", "group_replication"]
            }
        except MySQLClientError:
            logger.error("Failed to get installed plugins")
            raise

    def does_mysql_user_exist(self, username: str, hostname: str) -> bool:
        """Checks if a mysql user already exists."""
        user_existence_commands = (
            f"select user from mysql.user where user = '{username}' and host = '{hostname}'",
        )

        try:
            output = self._run_mysqlcli_script(
                user_existence_commands,
                user=self.server_config_user,
                password=self.server_config_password,
            )
            return len(output) == 1
        except MySQLClientError:
            logger.error(f"Failed to check for existence of mysql user {username}@{hostname}")
            raise MySQLCheckUserExistenceError()

    def configure_mysqlrouter_user(
        self, username: str, password: str, hostname: str, unit_name: str
    ) -> None:
        """Configure a mysqlrouter user and grant the appropriate permissions to the user."""
        try:
            escaped_mysqlrouter_user_attributes = json.dumps({"unit_name": unit_name}).replace(
                '"', r"\""
            )
            # Using server_config_user as we are sure it has create user grants
            create_mysqlrouter_user_commands = (
                "shell.connect_to_primary()",
                f"session.run_sql(\"CREATE USER '{username}'@'{hostname}' IDENTIFIED BY '{password}' ATTRIBUTE '{escaped_mysqlrouter_user_attributes}';\")",
            )

            # Using server_config_user as we are sure it has create user grants
            mysqlrouter_user_grant_commands = (
                "shell.connect_to_primary()",
                f"session.run_sql(\"GRANT CREATE USER ON *.* TO '{username}'@'{hostname}' WITH GRANT OPTION;\")",
                f"session.run_sql(\"GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE ON mysql_innodb_cluster_metadata.* TO '{username}'@'{hostname}';\")",
                f"session.run_sql(\"GRANT SELECT ON mysql.user TO '{username}'@'{hostname}';\")",
                f"session.run_sql(\"GRANT SELECT ON performance_schema.replication_group_members TO '{username}'@'{hostname}';\")",
                f"session.run_sql(\"GRANT SELECT ON performance_schema.replication_group_member_stats TO '{username}'@'{hostname}';\")",
                f"session.run_sql(\"GRANT SELECT ON performance_schema.global_variables TO '{username}'@'{hostname}';\")",
            )

            logger.debug(f"Configuring MySQLRouter {username=}")
            self._run_mysqlsh_script(
                "\n".join(create_mysqlrouter_user_commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
            # grant permissions to the newly created mysqlrouter user
            self._run_mysqlsh_script(
                "\n".join(mysqlrouter_user_grant_commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError:
            logger.error(f"Failed to configure mysqlrouter {username=}")
            raise MySQLConfigureRouterUserError

    def create_application_database_and_scoped_user(
        self,
        database_name: str,
        username: str,
        password: str,
        hostname: str,
        *,
        unit_name: Optional[str] = None,
        create_database: bool = True,
    ) -> None:
        """Create an application database and a user scoped to the created database."""
        attributes = {}
        if unit_name is not None:
            attributes["unit_name"] = unit_name
        try:
            # Using server_config_user as we are sure it has create database grants
            connect_command = ("shell.connect_to_primary()",)
            create_database_commands = (
                f'session.run_sql("CREATE DATABASE IF NOT EXISTS `{database_name}`;")',
            )

            escaped_user_attributes = json.dumps(attributes).replace('"', r"\"")
            # Using server_config_user as we are sure it has create user grants
            create_scoped_user_commands = (
                f"session.run_sql(\"CREATE USER `{username}`@`{hostname}` IDENTIFIED BY '{password}' ATTRIBUTE '{escaped_user_attributes}';\")",
                f'session.run_sql("GRANT USAGE ON *.* TO `{username}`@`{hostname}`;")',
                f'session.run_sql("GRANT ALL PRIVILEGES ON `{database_name}`.* TO `{username}`@`{hostname}`;")',
            )

            if create_database:
                commands = connect_command + create_database_commands + create_scoped_user_commands
            else:
                commands = connect_command + create_scoped_user_commands

            self._run_mysqlsh_script(
                "\n".join(commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError as e:
            logger.error(
                f"Failed to create application database {database_name} and scoped user {username}@{hostname}"
            )
            raise MySQLCreateApplicationDatabaseAndScopedUserError(e.message)

    @staticmethod
    def _get_statements_to_delete_users_with_attribute(
        attribute_name: str, attribute_value: str
    ) -> list[str]:
        """Generate mysqlsh statements to delete users with an attribute.

        If the value of the attribute is a string, include single quotes in the string.
        (e.g. "'bar'")
        """
        return [
            (
                "session.run_sql(\"SELECT IFNULL(CONCAT('DROP USER ', GROUP_CONCAT(QUOTE(USER),"
                " '@', QUOTE(HOST))), 'SELECT 1') INTO @sql FROM INFORMATION_SCHEMA.USER_ATTRIBUTES"
                f" WHERE ATTRIBUTE->'$.{attribute_name}'={attribute_value}\")"
            ),
            'session.run_sql("PREPARE stmt FROM @sql")',
            'session.run_sql("EXECUTE stmt")',
            'session.run_sql("DEALLOCATE PREPARE stmt")',
        ]

    def get_mysql_router_users_for_unit(
        self, *, relation_id: int, mysql_router_unit_name: str
    ) -> list[RouterUser]:
        """Get users for related MySQL Router unit."""
        relation_user = f"relation-{relation_id}"
        command = [
            (
                "result = session.run_sql(\"SELECT USER, ATTRIBUTE->>'$.router_id' FROM "
                f"INFORMATION_SCHEMA.USER_ATTRIBUTES WHERE ATTRIBUTE->'$.created_by_user'='{relation_user}' "
                f"AND ATTRIBUTE->'$.created_by_juju_unit'='{mysql_router_unit_name}'\")"
            ),
            "print(result.fetch_all())",
        ]
        try:
            output = self._run_mysqlsh_script(
                "\n".join(command),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError as e:
            logger.error(
                f"Failed to get MySQL Router users for relation {relation_id} and unit {mysql_router_unit_name}"
            )
            raise MySQLGetRouterUsersError(e.message)
        rows = json.loads(output)
        return [RouterUser(username=row[0], router_id=row[1]) for row in rows]

    def delete_users_for_unit(self, unit_name: str) -> None:
        """Delete users for a unit."""
        drop_users_command = [
            "shell.connect_to_primary()",
        ]
        drop_users_command.extend(
            self._get_statements_to_delete_users_with_attribute("unit_name", f"'{unit_name}'")
        )
        try:
            self._run_mysqlsh_script(
                "\n".join(drop_users_command),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError as e:
            logger.error(f"Failed to query and delete users for unit {unit_name}")
            raise MySQLDeleteUsersForUnitError(e.message)

    def delete_users_for_relation(self, username: str) -> None:
        """Delete users for a relation."""
        drop_users_command = [
            "shell.connect_to_primary()",
            f"session.run_sql(\"DROP USER IF EXISTS '{username}'@'%';\")",
        ]
        # If the relation is with a MySQL Router charm application, delete any users
        # created by that application.
        drop_users_command.extend(
            self._get_statements_to_delete_users_with_attribute("created_by_user", f"'{username}'")
        )
        try:
            self._run_mysqlsh_script(
                "\n".join(drop_users_command),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError as e:
            logger.error(f"Failed to delete {username=}")
            raise MySQLDeleteUsersForRelationError(e.message)

    def delete_user(self, username: str) -> None:
        """Delete user."""
        drop_user_command = [
            "shell.connect_to_primary()",
            f"session.run_sql(\"DROP USER `{username}`@'%'\")",
        ]
        try:
            self._run_mysqlsh_script(
                "\n".join(drop_user_command),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError as e:
            logger.error(f"Failed to delete user {username}")
            raise MySQLDeleteUserError(e.message)

    def remove_router_from_cluster_metadata(self, router_id: str) -> None:
        """Remove MySQL Router from InnoDB Cluster metadata."""
        command = [
            "cluster = dba.get_cluster()",
            f'cluster.remove_router_metadata("{router_id}")',
        ]
        try:
            self._run_mysqlsh_script(
                "\n".join(command),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError as e:
            logger.error(f"Failed to remove router from metadata with ID {router_id}")
            raise MySQLRemoveRouterFromMetadataError(e.message)

    def set_dynamic_variable(
        self,
        variable: str,
        value: str,
        persist: bool = False,
        instance_address: Optional[str] = None,
    ) -> None:
        """Set a dynamic variable value for the instance."""
        # escape variable values when needed
        if not re.match(r"^[0-9,a-z,A-Z$_]+$", value):
            value = f"`{value}`"

        logger.debug(f"Setting {variable=} to {value=}")
        set_var_command = (
            f'session.run_sql("SET {"PERSIST" if persist else "GLOBAL"} {variable}={value}")'
        )

        try:
            self._run_mysqlsh_script(
                set_var_command,
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user, instance_address),
            )
        except MySQLClientError:
            logger.error(f"Failed to set {variable=} to {value=}")
            raise MySQLSetVariableError

    def get_variable_value(self, variable: str) -> str:
        """Get the value of a variable."""
        get_var_command = [
            f"result = session.run_sql(\"SHOW VARIABLES LIKE '{variable}'\")",
            "print(result.fetch_all())",
        ]

        try:
            output = self._run_mysqlsh_script(
                "\n".join(get_var_command),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError:
            logger.error(f"Failed to get value for {variable=}")
            raise MySQLGetVariableError

        rows = json.loads(output)
        return rows[0][1]

    def configure_instance(self, create_cluster_admin: bool = True) -> None:
        """Configure the instance to be used in an InnoDB cluster."""
        options = {
            "restart": "true",
        }

        if create_cluster_admin:
            options.update({
                "clusterAdmin": self.cluster_admin_user,
                "clusterAdminPassword": self.cluster_admin_password,
            })

        configure_instance_command = f"dba.configure_instance(options={options})"

        try:
            logger.debug(f"Configuring instance for InnoDB on {self.instance_address}")
            self._run_mysqlsh_script(
                configure_instance_command,
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
            self.wait_until_mysql_connection()
        except MySQLClientError:
            logger.error(f"Failed to configure instance {self.instance_address}")
            raise MySQLConfigureInstanceError

    def create_cluster(self, unit_label: str) -> None:
        """Create an InnoDB cluster with Group Replication enabled."""
        # defaulting group replication communication stack to MySQL instead of XCOM
        # since it will encrypt gr members communication by default
        options = {
            "communicationStack": "MySQL",
        }

        commands = (
            f"cluster = dba.create_cluster('{self.cluster_name}', {options})",
            f"cluster.set_instance_option('{self.instance_address}', 'label', '{unit_label}')",
        )

        try:
            logger.debug(f"Creating a MySQL InnoDB cluster on {self.instance_address}")
            self._run_mysqlsh_script(
                "\n".join(commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError:
            logger.error(f"Failed to create cluster on instance: {self.instance_address}")
            raise MySQLCreateClusterError

    def create_cluster_set(self) -> None:
        """Create a cluster set for the cluster on cluster primary."""
        commands = (
            "shell.connect_to_primary()",
            f"cluster = dba.get_cluster('{self.cluster_name}')",
            f"cluster.create_cluster_set('{self.cluster_set_name}')",
        )

        try:
            logger.debug(f"Creating cluster set name {self.cluster_set_name}")
            self._run_mysqlsh_script(
                "\n".join(commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError:
            logger.error("Failed to create cluster-set")
            raise MySQLCreateClusterSetError from None

    def create_replica_cluster(
        self,
        endpoint: str,
        replica_cluster_name: str,
        instance_label: str,
        donor: Optional[str] = None,
        method: Optional[str] = "auto",
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

        commands = (
            "shell.connect_to_primary()",
            "cs = dba.get_cluster_set()",
            f"repl_cluster = cs.create_replica_cluster('{endpoint}','{replica_cluster_name}', {options})",
            f"repl_cluster.set_instance_option('{endpoint}', 'label', '{instance_label}')",
        )

        try:
            logger.debug(f"Creating replica cluster {replica_cluster_name}")

            # hide exception logging on auto try
            log_exception = method == "auto"
            self._run_mysqlsh_script(
                "\n".join(commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
                exception_as_warning=log_exception,
            )
        except MySQLClientError:
            if method == "auto":
                logger.warning(
                    "Failed to create replica cluster with auto method, fallback to clone method"
                )
                self.create_replica_cluster(
                    endpoint,
                    replica_cluster_name,
                    instance_label,
                    donor,
                    method="clone",
                )
            else:
                logger.error("Failed to create replica cluster")
                raise MySQLCreateReplicaClusterError

    def promote_cluster_to_primary(self, cluster_name: str, force: bool = False) -> None:
        """Promote a cluster to become the primary cluster on the cluster set."""
        commands = (
            "shell.connect_to_primary()",
            "cs = dba.get_cluster_set()",
            (
                f"cs.force_primary_cluster('{cluster_name}')"
                if force
                else f"cs.set_primary_cluster('{cluster_name}')"
            ),
        )

        if force:
            logger.warning(f"Promoting {cluster_name=} to primary with {force=}")
        else:
            logger.debug(f"Promoting {cluster_name=} to primary with {force=}")

        try:
            self._run_mysqlsh_script(
                "\n".join(commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError:
            logger.error("Failed to promote cluster to primary")
            raise MySQLPromoteClusterToPrimaryError

    def fence_writes(self) -> None:
        """Fence writes on the primary cluster."""
        commands = (
            "c = dba.get_cluster()",
            "c.fence_writes()",
        )

        try:
            self._run_mysqlsh_script(
                "\n".join(commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError:
            logger.error("Failed to fence writes on cluster")
            raise MySQLFencingWritesError

    def unfence_writes(self) -> None:
        """Unfence writes on the primary cluster and reset read_only flag."""
        commands = (
            "c = dba.get_cluster()",
            "c.unfence_writes()",
            "session.run_sql('SET GLOBAL read_only=OFF')",
        )

        try:
            self._run_mysqlsh_script(
                "\n".join(commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError:
            logger.error("Failed to resume writes on primary cluster")
            raise MySQLFencingWritesError

    def is_cluster_writes_fenced(self) -> Optional[bool]:
        """Check if the cluster is fenced against writes."""
        status = self.get_cluster_status()
        if not status:
            return

        return status["defaultreplicaset"]["status"] == MySQLClusterState.FENCED

    def is_cluster_in_cluster_set(self, cluster_name: str) -> Optional[bool]:
        """Check if a cluster is in the cluster set."""
        cs_status = self.get_cluster_set_status(extended=0)

        if cs_status is None:
            return None

        return cluster_name in cs_status["clusters"]

    def cluster_metadata_exists(self, from_instance: str) -> bool:
        """Check if this cluster metadata exists on database."""
        check_cluster_metadata_commands = (
            "result = session.run_sql(\"SHOW DATABASES LIKE 'mysql_innodb_cluster_metadata'\")",
            "content = result.fetch_all()",
            "if content:",
            (
                '  result = session.run_sql("SELECT cluster_name FROM mysql_innodb_cluster_metadata'
                f".clusters where cluster_name = '{self.cluster_name}';\")"
            ),
            "  print(bool(result.fetch_one()))",
            "else:",
            "  print(False)",
        )

        try:
            output = self._run_mysqlsh_script(
                "\n".join(check_cluster_metadata_commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user, from_instance),
                timeout=60,
                exception_as_warning=True,
            )
        except MySQLClientError:
            logger.warning(f"Failed to check if cluster metadata exists {from_instance=}")
            return False

        return output.strip() == "True"

    def rejoin_cluster(self, cluster_name) -> None:
        """Try to rejoin a cluster to the cluster set."""
        commands = (
            "shell.connect_to_primary()",
            "cs = dba.get_cluster_set()",
            f"cs.rejoin_cluster('{cluster_name}')",
        )

        try:
            logger.debug(f"Rejoining {cluster_name=}")
            self._run_mysqlsh_script(
                "\n".join(commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )

            logger.info(f"Rejoined {cluster_name=}")
        except MySQLClientError:
            logger.error("Failed to rejoin cluster")
            raise MySQLRejoinClusterError

    def remove_replica_cluster(self, replica_cluster_name: str, force: bool = False) -> None:
        """Remove a replica cluster from the cluster-set."""
        commands = [
            "shell.connect_to_primary()",
            "cs = dba.get_cluster_set()",
        ]
        if force:
            commands.append(f"cs.remove_cluster('{replica_cluster_name}', {{'force': True}})")
        else:
            commands.append(f"cs.remove_cluster('{replica_cluster_name}')")

        try:
            logger.debug(f"Removing replica cluster {replica_cluster_name}")
            self._run_mysqlsh_script(
                "\n".join(commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError:
            logger.error("Failed to remove replica cluster")
            raise MySQLRemoveReplicaClusterError

    def initialize_juju_units_operations_table(self) -> None:
        """Initialize the mysql.juju_units_operations table using the serverconfig user."""
        initialize_table_commands = (
            "DROP TABLE IF EXISTS mysql.juju_units_operations",
            "CREATE TABLE mysql.juju_units_operations (task varchar(20), executor "
            "varchar(20), status varchar(20), primary key(task))",
            f"INSERT INTO mysql.juju_units_operations values ('{UNIT_TEARDOWN_LOCKNAME}', '', "
            "'not-started') ON DUPLICATE KEY UPDATE executor = '', status = 'not-started'",
            f"INSERT INTO mysql.juju_units_operations values ('{UNIT_ADD_LOCKNAME}', '', "
            "'not-started') ON DUPLICATE KEY UPDATE executor = '', status = 'not-started'",
        )

        try:
            logger.debug(
                f"Initializing the juju_units_operations table on {self.instance_address}"
            )

            self._run_mysqlcli_script(
                initialize_table_commands,
                user=self.server_config_user,
                password=self.server_config_password,
            )
        except MySQLClientError:
            logger.error("Failed to initialize mysql.juju_units_operations table with error")
            raise MySQLInitializeJujuOperationsTableError

    def add_instance_to_cluster(
        self,
        *,
        instance_address: str,
        instance_unit_label: str,
        from_instance: Optional[str] = None,
        lock_instance: Optional[str] = None,
        method: str = "auto",
    ) -> None:
        """Add an instance to the InnoDB cluster."""
        options = {
            "password": self.cluster_admin_password,
            "label": instance_unit_label,
        }

        local_lock_instance = lock_instance or from_instance or self.instance_address

        if not self._acquire_lock(
            local_lock_instance,
            instance_unit_label,
            UNIT_ADD_LOCKNAME,
        ):
            raise MySQLLockAcquisitionError("Lock not acquired")

        connect_instance = from_instance or self.instance_address
        connect_commands = (
            f"cluster = dba.get_cluster('{self.cluster_name}')",
            "shell.options['dba.restartWaitTimeout'] = 3600",
        )

        # Prefer "auto" recovery method, but if it fails, try "clone"
        try:
            options["recoveryMethod"] = method
            add_instance_command = (
                f"cluster.add_instance('{self.cluster_admin_user}@{instance_address}', {options})",
            )

            logger.info(
                f"Adding instance {instance_address}/{instance_unit_label} to {self.cluster_name=}"
                f"with recovery {method=}"
            )
            # hide exception logging on auto try
            log_exception = method == "auto"
            self._run_mysqlsh_script(
                "\n".join(connect_commands + add_instance_command),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user, connect_instance),
                exception_as_warning=log_exception,
            )

        except MySQLClientError:
            if method == "clone":
                logger.error(
                    f"Failed to add {instance_address=} to {self.cluster_name=} on {self.instance_address=}",
                )
                raise MySQLAddInstanceToClusterError

            logger.debug(
                f"Cannot add {instance_address=} to {self.cluster_name=} with recovery {method=}. Trying method 'clone'"
            )
            self.add_instance_to_cluster(
                instance_address=instance_address,
                instance_unit_label=instance_unit_label,
                from_instance=from_instance,
                lock_instance=lock_instance,
                method="clone",
            )
        finally:
            # always release the lock
            self._release_lock(local_lock_instance, instance_unit_label, UNIT_ADD_LOCKNAME)

    def is_instance_configured_for_innodb(
        self, instance_address: str, instance_unit_label: str
    ) -> bool:
        """Confirm if instance is configured for use in an InnoDB cluster."""
        commands = (
            "instance_configured = dba.check_instance_configuration()['status'] == 'ok'",
            'print("INSTANCE_CONFIGURED" if instance_configured else "INSTANCE_NOT_CONFIGURED")',
        )

        try:
            logger.debug(
                f"Confirming instance {instance_address}/{instance_unit_label} configuration for InnoDB"
            )

            output = self._run_mysqlsh_script(
                "\n".join(commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user, instance_address),
            )
            return "INSTANCE_CONFIGURED" in output
        except MySQLClientError as e:
            # confirmation can fail if the clusteradmin user does not yet exist on the instance
            logger.warning(
                f"Failed to confirm instance configuration for {instance_address} with error {e.message}",
            )
            return False

    def drop_group_replication_metadata_schema(self) -> None:
        """Drop the group replication metadata schema from current unit."""
        commands = "dba.drop_metadata_schema()"

        try:
            self._run_mysqlsh_script(
                commands,
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError:
            logger.error("Failed to drop group replication metadata schema")

    def are_locks_acquired(self, from_instance: Optional[str] = None) -> bool:
        """Report if any topology change is being executed."""
        commands = (
            "result = session.run_sql(\"SELECT COUNT(*) FROM mysql.juju_units_operations WHERE status='in-progress';\")",
            "print(f'<LOCKS>{result.fetch_one()[0]}</LOCKS>')",
        )
        try:
            output = self._run_mysqlsh_script(
                "\n".join(commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user, from_instance),
            )
        except MySQLClientError:
            # log error and fallback to assuming topology is changing
            logger.error("Failed to get locks count")
            return True

        matches = re.search(r"<LOCKS>(\d)</LOCKS>", output)

        return int(matches.group(1)) > 0 if matches else False

    def rescan_cluster(
        self,
        from_instance: Optional[str] = None,
        remove_instances: bool = False,
        add_instances: bool = False,
    ) -> None:
        """Rescan the cluster for topology changes."""
        options = {}
        if remove_instances:
            options["removeInstances"] = "auto"
        if add_instances:
            options["addInstances"] = "auto"

        rescan_cluster_commands = (
            f"cluster = dba.get_cluster('{self.cluster_name}')",
            f"cluster.rescan({options})",
        )
        try:
            logger.debug("Rescanning cluster")
            self._run_mysqlsh_script(
                "\n".join(rescan_cluster_commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user, from_instance),
            )
        except MySQLClientError as e:
            logger.error("Error rescanning the cluster")
            raise MySQLRescanClusterError(e.message)

    def is_instance_in_cluster(self, unit_label: str) -> bool:
        """Confirm if instance is in the cluster."""
        if not self.cluster_metadata_exists(self.instance_address):
            # early return if instance has no cluster metadata
            return False

        commands = (
            f"cluster = dba.get_cluster('{self.cluster_name}')",
            f"print(cluster.status()['defaultReplicaSet']['topology'].get('{unit_label}', {{}}).get('status', 'NOT_A_MEMBER'))",
        )

        try:
            logger.debug(f"Checking existence of unit {unit_label} in cluster {self.cluster_name}")

            output = self._run_mysqlsh_script(
                "\n".join(commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
            return (
                MySQLMemberState.ONLINE in output.lower()
                or MySQLMemberState.RECOVERING in output.lower()
            )
        except MySQLClientError:
            # confirmation can fail if the clusteradmin user does not yet exist on the instance
            logger.debug(
                f"Failed to confirm existence of unit {unit_label} in cluster {self.cluster_name}"
            )
            return False

    @retry(
        wait=wait_fixed(2),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(TimeoutError),
    )
    def get_cluster_status(
        self, from_instance: Optional[str] = None, extended: Optional[bool] = False
    ) -> Optional[dict]:
        """Get the cluster status dictionary."""
        options = {"extended": extended}
        status_commands = (
            f"cluster = dba.get_cluster('{self.cluster_name}')",
            f"print(cluster.status({options}))",
        )

        try:
            output = self._run_mysqlsh_script(
                "\n".join(status_commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user, from_instance),
                timeout=30,
            )
            output_dict = json.loads(output.lower())
            return output_dict
        except MySQLClientError:
            logger.error(f"Failed to get cluster status for {self.cluster_name}")

    def get_cluster_set_status(
        self, extended: Optional[int] = 1, from_instance: Optional[str] = None
    ) -> Optional[dict]:
        """Get the cluster-set status dictionary."""
        options = {"extended": extended}
        status_commands = (
            "cs = dba.get_cluster_set()",
            f"print(cs.status({options}))",
        )

        try:
            output = self._run_mysqlsh_script(
                "\n".join(status_commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user, from_instance),
                timeout=150,
                exception_as_warning=True,
            )
            output_dict = json.loads(output.lower())
            return output_dict
        except MySQLClientError:
            logger.warning("Failed to get cluster set status")

    def get_cluster_names(self) -> set[str]:
        """Get the names of the clusters in the cluster set."""
        status = self.get_cluster_set_status()
        if not status:
            return set()
        return set(status["clusters"])

    def get_replica_cluster_status(self, replica_cluster_name: Optional[str] = None) -> str:
        """Get the replica cluster status."""
        if not replica_cluster_name:
            replica_cluster_name = self.cluster_name
        status_commands = (
            "cs = dba.get_cluster_set()",
            f"print(cs.status(extended=1)['clusters']['{replica_cluster_name}']['globalStatus'])",
        )

        try:
            output = self._run_mysqlsh_script(
                "\n".join(status_commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
                timeout=150,
                exception_as_warning=True,
            )
            return output.lower().strip()
        except MySQLClientError:
            logger.warning(f"Failed to get replica cluster status for {replica_cluster_name}")
            return "unknown"

    def get_cluster_node_count(
        self,
        from_instance: Optional[str] = None,
        node_status: Optional[MySQLMemberState] = None,
    ) -> int:
        """Retrieve current count of cluster nodes, optionally filtered by status."""
        if not node_status:
            query = "SELECT COUNT(*) FROM performance_schema.replication_group_members"
        else:
            query = (
                "SELECT COUNT(*) FROM performance_schema.replication_group_members"
                f" WHERE member_state = '{node_status.value.upper()}'"
            )
        size_commands = (
            f'result = session.run_sql("{query}")',
            'print(f"<NODES>{result.fetch_one()[0]}</NODES>")',
        )

        try:
            output = self._run_mysqlsh_script(
                "\n".join(size_commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user, from_instance),
                timeout=30,
                exception_as_warning=True,
            )
        except MySQLClientError:
            logger.warning("Failed to get node count")
            return 0

        matches = re.search(r"<NODES>(\d)</NODES>", output)

        return int(matches.group(1)) if matches else 0

    def get_cluster_endpoints(self, get_ips: bool = True) -> Tuple[str, str, str]:
        """Return (rw, ro, ofline) endpoints tuple names or IPs."""
        status = self.get_cluster_status()

        if not status:
            raise MySQLGetClusterEndpointsError("Failed to get endpoints from cluster status")

        topology = status["defaultreplicaset"]["topology"]

        def _get_host_ip(host: str) -> str:
            try:
                port = None
                if ":" in host:
                    host, port = host.split(":")

                host_ip = socket.gethostbyname(host)
                return f"{host_ip}:{port}" if port else host_ip
            except socket.gaierror:
                raise MySQLGetClusterEndpointsError(f"Failed to query IP for host {host}")

        ro_endpoints = {
            _get_host_ip(v["address"]) if get_ips else v["address"]
            for v in topology.values()
            if v["mode"] == "r/o" and v["status"] == MySQLMemberState.ONLINE
        }

        if self.is_cluster_replica():
            # replica return global primary address
            global_primary = self.get_cluster_set_global_primary_address()
            if not global_primary:
                raise MySQLGetClusterEndpointsError("Failed to get global primary address")
            rw_endpoints = {_get_host_ip(global_primary) if get_ips else global_primary}
        else:
            rw_endpoints = {
                _get_host_ip(v["address"]) if get_ips else v["address"]
                for v in topology.values()
                if v["mode"] == "r/w" and v["status"] == MySQLMemberState.ONLINE
            }
        # won't get offline endpoints to IP as they maybe unreachable
        no_endpoints = {
            v["address"] for v in topology.values() if v["status"] != MySQLMemberState.ONLINE
        }

        return ",".join(rw_endpoints), ",".join(ro_endpoints), ",".join(no_endpoints)

    def execute_remove_instance(
        self, connect_instance: Optional[str] = None, force: bool = False
    ) -> None:
        """Execute the remove_instance() script with mysqlsh.

        Args:
            connect_instance: (optional) The instance from where to run the remove_instance()
            force: (optional) Whether to force the removal of the instance
        """
        remove_instance_options = {
            "password": self.cluster_admin_password,
            "force": "true" if force else "false",
        }
        remove_instance_commands = (
            f"cluster = dba.get_cluster('{self.cluster_name}')",
            "cluster.remove_instance("
            f"'{self.cluster_admin_user}@{self.instance_address}', {remove_instance_options})",
        )
        self._run_mysqlsh_script(
            "\n".join(remove_instance_commands),
            user=self.server_config_user,
            password=self.server_config_password,
            host=self.instance_def(self.server_config_user, connect_instance),
        )

    @retry(
        retry=retry_if_exception_type(MySQLRemoveInstanceRetryError),
        stop=stop_after_attempt(15),
        reraise=True,
        wait=wait_random(min=4, max=30),
    )
    def remove_instance(  # noqa: C901
        self, unit_label: str, lock_instance: Optional[str] = None
    ) -> None:
        """Remove instance from the cluster.

        This method is called from each unit being torn down, thus we must obtain
        locks on the cluster primary. There is a retry mechanism for any issues
        obtaining the lock, removing instances/dissolving the cluster, or releasing
        the lock.
        """
        remaining_cluster_member_addresses = []
        skip_release_lock = False
        try:
            # Get the cluster primary's address to direct lock acquisition request to.
            primary_address = self.get_cluster_primary_address()
            if not primary_address:
                raise MySQLRemoveInstanceRetryError(
                    "Unable to retrieve the cluster primary's address"
                )

            # Attempt to acquire a lock on the primary instance
            acquired_lock = self._acquire_lock(
                lock_instance or primary_address, unit_label, UNIT_TEARDOWN_LOCKNAME
            )
            if not acquired_lock:
                logger.debug(f"Failed to acquire lock to remove unit {unit_label}. Retrying.")
                raise MySQLRemoveInstanceRetryError("Did not acquire lock to remove unit")

            # Remove instance from cluster, or dissolve cluster if no other members remain
            logger.debug(
                f"Removing instance {self.instance_address} from cluster {self.cluster_name}"
            )

            if self.get_cluster_node_count() == 1:
                # Last instance in the cluster, dissolve the cluster
                cluster_names = self.get_cluster_names()
                if len(cluster_names) > 1 and not self.is_cluster_replica():
                    # when last instance from a primary cluster belonging to a cluster set
                    # promote another cluster to primary prior to dissolving
                    another_cluster = (cluster_names - {self.cluster_name}).pop()
                    self.promote_cluster_to_primary(another_cluster)
                    # update lock instance
                    lock_instance = self.get_cluster_set_global_primary_address()
                    self.remove_replica_cluster(self.cluster_name)
                else:
                    skip_release_lock = True
                self.dissolve_cluster()

            else:
                # Get remaining cluster member addresses before calling mysqlsh.remove_instance()
                remaining_cluster_member_addresses, valid = self._get_cluster_member_addresses(
                    exclude_unit_labels=[unit_label]
                )
                if not valid:
                    raise MySQLRemoveInstanceRetryError(
                        "Unable to retrieve cluster member addresses"
                    )

                # Just remove instance
                self.execute_remove_instance(force=True)
        except MySQLClientError as e:
            # In case of an error, raise an error and retry
            logger.warning(
                f"Failed to acquire lock and remove instance {self.instance_address} with error {e.message}"
            )
            raise MySQLRemoveInstanceRetryError(e.message)
        finally:
            # There is no need to release the lock if single cluster was dissolved
            if skip_release_lock:
                return

            try:
                if not lock_instance:
                    if len(remaining_cluster_member_addresses) == 0:
                        raise MySQLRemoveInstanceRetryError(
                            "No remaining instance to query cluster primary from."
                        )

                    # Retrieve the cluster primary's address again (in case the old primary is
                    # scaled down)
                    # Release the lock by making a request to this primary member's address
                    lock_instance = self.get_cluster_primary_address(
                        connect_instance_address=remaining_cluster_member_addresses[0]
                    )
                    if not lock_instance:
                        raise MySQLRemoveInstanceError(
                            "Unable to retrieve the address of the cluster primary"
                        )

                self._release_lock(lock_instance, unit_label, UNIT_TEARDOWN_LOCKNAME)
            except MySQLClientError as e:
                # Raise an error that does not lead to a retry of this method
                logger.error(f"Failed to release lock on {unit_label}")
                raise MySQLRemoveInstanceError(e.message)

    def dissolve_cluster(self) -> None:
        """Dissolve the cluster independently of the unit teardown process."""
        logger.debug(f"Dissolving cluster {self.cluster_name}")
        dissolve_cluster_commands = (
            f"cluster = dba.get_cluster('{self.cluster_name}')",
            "cluster.dissolve({'force': 'true'})",
        )
        self._run_mysqlsh_script(
            "\n".join(dissolve_cluster_commands),
            user=self.server_config_user,
            password=self.server_config_password,
            host=self.instance_def(self.server_config_user),
        )

    def _acquire_lock(self, primary_address: str, unit_label: str, lock_name: str) -> bool:
        """Attempts to acquire a lock by using the mysql.juju_units_operations table."""
        logger.debug(
            f"Attempting to acquire lock {lock_name} on {primary_address} for unit {unit_label}"
        )

        acquire_lock_commands = (
            (
                f"session.run_sql(\"UPDATE mysql.juju_units_operations SET executor='{unit_label}',"
                f" status='in-progress' WHERE task='{lock_name}' AND executor='';\")"
            ),
            (
                'acquired_lock = session.run_sql("SELECT count(*) FROM mysql.juju_units_operations'
                f" WHERE task='{lock_name}' AND executor='{unit_label}';\").fetch_one()[0]"
            ),
            "print(f'<ACQUIRED_LOCK>{acquired_lock}</ACQUIRED_LOCK>')",
        )

        try:
            output = self._run_mysqlsh_script(
                "\n".join(acquire_lock_commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user, primary_address),
            )
        except MySQLClientError:
            logger.debug(f"Failed to acquire lock {lock_name}")
            return False
        matches = re.search(r"<ACQUIRED_LOCK>(\d)</ACQUIRED_LOCK>", output)
        if not matches:
            return False

        return bool(int(matches.group(1)))

    def _release_lock(self, primary_address: str, unit_label: str, lock_name: str) -> None:
        """Releases a lock in the mysql.juju_units_operations table."""
        logger.debug(f"Releasing {lock_name=} @{primary_address=} for {unit_label=}")

        release_lock_commands = (
            "r = session.run_sql(\"UPDATE mysql.juju_units_operations SET executor='', status='not-started'"
            f" WHERE task='{lock_name}' AND executor='{unit_label}';\")",
            "print(r.get_affected_items_count())",
        )
        affected_rows = self._run_mysqlsh_script(
            "\n".join(release_lock_commands),
            user=self.server_config_user,
            password=self.server_config_password,
            host=self.instance_def(self.server_config_user, primary_address),
        )
        if affected_rows:
            if int(affected_rows) == 0:
                logger.warning("No lock to release")
            else:
                logger.debug(f"{lock_name=} released for {unit_label=}")

    def _get_cluster_member_addresses(self, exclude_unit_labels: List = []) -> Tuple[List, bool]:
        """Get the addresses of the cluster's members."""
        logger.debug(f"Getting cluster member addresses, excluding units {exclude_unit_labels}")

        get_cluster_members_commands = (
            f"cluster = dba.get_cluster('{self.cluster_name}')",
            (
                "member_addresses = ','.join([member['address'] for label, member in "
                f"cluster.status()['defaultReplicaSet']['topology'].items() if label not in {exclude_unit_labels}])"
            ),
            "print(f'<MEMBER_ADDRESSES>{member_addresses}</MEMBER_ADDRESSES>')",
        )

        output = self._run_mysqlsh_script(
            "\n".join(get_cluster_members_commands),
            user=self.server_config_user,
            password=self.server_config_password,
            host=self.instance_def(self.server_config_user),
        )
        matches = re.search(r"<MEMBER_ADDRESSES>(.*)</MEMBER_ADDRESSES>", output)

        if not matches:
            return ([], False)

        # Filter out any empty values (in case there are no members)
        member_addresses = [
            member_address for member_address in matches.group(1).split(",") if member_address
        ]

        return (member_addresses, "<MEMBER_ADDRESSES>" in output)

    def get_cluster_primary_address(
        self, connect_instance_address: Optional[str] = None
    ) -> Optional[str]:
        """Get the cluster primary's address."""
        logger.debug("Getting cluster primary member's address")

        get_cluster_primary_commands = (
            "shell.connect_to_primary()",
            "primary_address = shell.parse_uri(session.uri)['host']",
            "print(f'<PRIMARY_ADDRESS>{primary_address}</PRIMARY_ADDRESS>')",
        )

        try:
            output = self._run_mysqlsh_script(
                "\n".join(get_cluster_primary_commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user, connect_instance_address),
            )
        except MySQLClientError as e:
            logger.warning("Failed to get cluster primary addresses")
            raise MySQLGetClusterPrimaryAddressError(e.message)
        matches = re.search(r"<PRIMARY_ADDRESS>(.+)</PRIMARY_ADDRESS>", output)

        if not matches:
            return None

        return matches.group(1)

    def get_cluster_set_global_primary_address(
        self, connect_instance_address: Optional[str] = None
    ) -> Optional[str]:
        """Get the cluster set global primary's address."""
        logger.debug("Getting cluster set global primary member's address")

        get_cluster_set_global_primary_commands = (
            "cs = dba.get_cluster_set()",
            "global_primary = cs.status()['globalPrimaryInstance']",
            "print(f'<PRIMARY_ADDRESS>{global_primary}</PRIMARY_ADDRESS>')",
        )

        try:
            output = self._run_mysqlsh_script(
                "\n".join(get_cluster_set_global_primary_commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user, connect_instance_address),
            )
        except MySQLClientError as e:
            logger.warning("Failed to get cluster set global primary addresses")
            raise MySQLGetClusterPrimaryAddressError(e.message)
        matches = re.search(r"<PRIMARY_ADDRESS>(.+)</PRIMARY_ADDRESS>", output)

        if not matches:
            return None

        address = matches.group(1)
        if ":" in address:
            # strip port from address
            address = address.split(":")[0]

        return address

    def get_primary_label(self) -> Optional[str]:
        """Get the label of the cluster's primary."""
        status = self.get_cluster_status()
        if not status:
            return None
        for label, value in status["defaultreplicaset"]["topology"].items():
            if value["memberrole"] == "primary":
                return label

    def is_unit_primary(self, unit_label: str) -> bool:
        """Test if a given unit is the cluster primary."""
        primary_label = self.get_primary_label()
        return primary_label == unit_label

    def set_cluster_primary(self, new_primary_address: str) -> None:
        """Set the cluster primary."""
        logger.debug(f"Setting cluster primary to {new_primary_address}")

        set_cluster_primary_commands = (
            "shell.connect_to_primary()",
            f"cluster = dba.get_cluster('{self.cluster_name}')",
            f"cluster.set_primary_instance('{new_primary_address}')",
        )
        try:
            self._run_mysqlsh_script(
                "\n".join(set_cluster_primary_commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError as e:
            logger.error("Failed to set cluster primary")
            raise MySQLSetClusterPrimaryError(e.message)

    def verify_server_upgradable(self, instance: Optional[str] = None) -> None:
        """Wrapper for API check_for_server_upgrade."""
        # use cluster admin user to enforce standard port usage
        check_command = [
            "try:",
            "    util.check_for_server_upgrade(options={'outputFormat': 'JSON'})",
            "except ValueError:",  # ValueError is raised for same version check
            "    if session.run_sql('select @@version').fetch_all()[0][0].split('-')[0] in shell.version:",
            "        print('SAME_VERSION')",
            "    else:",
            "        raise",
        ]

        def _strip_output(output: str):
            # output may need first line stripped to
            # remove information header text
            if not output.split("\n")[0].startswith("{"):
                return "\n".join(output.split("\n")[1:])
            return output

        try:
            output = self._run_mysqlsh_script(
                "\n".join(check_command),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user, instance),
            )
            if "SAME_VERSION" in output:
                return
            result = json.loads(_strip_output(output))
            if result["errorCount"] == 0:
                return
            raise MySQLServerNotUpgradableError(result.get("summary"))
        except MySQLClientError:
            raise MySQLServerNotUpgradableError("Failed to check for server upgrade")

    def get_mysql_version(self) -> Optional[str]:
        """Get the running mysqld version."""
        logger.debug("Getting InnoDB version")

        get_version_commands = (
            'result = session.run_sql("SELECT version()")',
            'print(f"<VERSION>{result.fetch_one()[0]}</VERSION>")',
        )

        try:
            output = self._run_mysqlsh_script(
                "\n".join(get_version_commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError as e:
            logger.warning("Failed to get workload version")
            raise MySQLGetMySQLVersionError(e.message)

        matches = re.search(r"<VERSION>(.+)</VERSION>", output)

        if not matches:
            return None

        return matches.group(1)

    def grant_privileges_to_user(
        self, username, hostname, privileges, with_grant_option=False
    ) -> None:
        """Grants specified privileges to the provided database user."""
        grant_privileges_commands = (
            "shell.connect_to_primary()",
            (
                f"session.run_sql(\"GRANT {', '.join(privileges)} ON *.* TO '{username}'@'{hostname}'"
                f'{" WITH GRANT OPTION" if with_grant_option else ""}")'
            ),
        )

        try:
            self._run_mysqlsh_script(
                "\n".join(grant_privileges_commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError as e:
            logger.warning(f"Failed to grant privileges to user {username}@{hostname}")
            raise MySQLGrantPrivilegesToUserError(e.message)

    def update_user_password(self, username: str, new_password: str, host: str = "%") -> None:
        """Updates user password in MySQL database."""
        # password is set on the global primary
        if not (instance_address := self.get_cluster_set_global_primary_address()):
            raise MySQLCheckUserExistenceError("No primary found")

        update_user_password_commands = (
            f"session.run_sql(\"ALTER USER '{username}'@'{host}' IDENTIFIED BY '{new_password}';\")",
            'session.run_sql("FLUSH PRIVILEGES;")',
        )

        logger.debug(f"Updating password for {username}.")
        try:
            self._run_mysqlsh_script(
                "\n".join(update_user_password_commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user, instance_address),
            )
        except MySQLClientError:
            logger.error(f"Failed to update user password for user {username}")
            raise MySQLCheckUserExistenceError

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_fixed(GET_MEMBER_STATE_TIME))
    def get_member_state(self) -> Tuple[str, str]:
        """Get member status (MEMBER_STATE, MEMBER_ROLE) in the cluster."""
        member_state_query = (
            "SELECT MEMBER_STATE, MEMBER_ROLE, MEMBER_ID, @@server_uuid"
            " FROM performance_schema.replication_group_members",
        )

        try:
            output = self._run_mysqlcli_script(
                member_state_query,
                user=self.cluster_admin_user,
                password=self.cluster_admin_password,
                timeout=10,
            )
        except MySQLClientError:
            logger.error("Failed to get member state: mysqld daemon is down")
            raise MySQLUnableToGetMemberStateError

        # output is like:
        # [('ONLINE',
        #  'PRIMARY',
        #  '1de30105-ce16-11ef-bb27-00163e3cb985',
        #  '1de30105-ce16-11ef-bb27-00163e3cb985'), (...)]
        if len(output) == 0:
            raise MySQLNoMemberStateError("No member state retrieved")

        def lower_or_unknown(value) -> str:
            return value.lower() if value else "unknown"

        if len(output) == 1:
            # Instance just know it own state
            # sometimes member_id is not populated
            return lower_or_unknown(output[0][0]), lower_or_unknown(output[0][1])

        for row in output:
            # results will be like:
            # ['online', 'primary', 'a6c00302-1c07-11ee-bca1-...', 'a6c00302-1c07-11ee-bca1-...']
            if row[2] == row[3]:
                # filter server uuid
                return lower_or_unknown(row[0]), lower_or_unknown(row[1])

        raise MySQLNoMemberStateError("No member state retrieved")

    def is_cluster_auto_rejoin_ongoing(self):
        """Check if the instance is performing a cluster auto rejoin operation."""
        cluster_auto_rejoin_command = (
            "cursor = session.run_sql(\"SELECT work_completed, work_estimated FROM performance_schema.events_stages_current WHERE event_name LIKE '%auto-rejoin%'\")",
            "result = cursor.fetch_one() or [0,0]",
            "print(f'<COMPLETED_ATTEMPTS>{result[0]}</COMPLETED_ATTEMPTS>')",
            "print(f'<ESTIMATED_ATTEMPTS>{result[1]}</ESTIMATED_ATTEMPTS>')",
        )

        try:
            output = self._run_mysqlsh_script(
                "\n".join(cluster_auto_rejoin_command),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError as e:
            logger.error("Failed to get cluster auto-rejoin information", exc_info=e)
            raise

        completed_matches = re.search(r"<COMPLETED_ATTEMPTS>(\d)</COMPLETED_ATTEMPTS>", output)
        estimated_matches = re.search(r"<ESTIMATED_ATTEMPTS>(\d)</ESTIMATED_ATTEMPTS>", output)

        return int(completed_matches.group(1)) < int(estimated_matches.group(1))

    def is_cluster_replica(self, from_instance: Optional[str] = None) -> Optional[bool]:
        """Check if this cluster is a replica in a cluster set."""
        cs_status = self.get_cluster_set_status(extended=0, from_instance=from_instance)
        if not cs_status:
            return

        return cs_status["clusters"][self.cluster_name.lower()]["clusterrole"] == "replica"

    def get_cluster_set_name(self, from_instance: Optional[str] = None) -> Optional[str]:
        """Get cluster set name."""
        cs_status = self.get_cluster_set_status(extended=0, from_instance=from_instance)
        if not cs_status:
            return None

        return cs_status["domainname"]

    def stop_group_replication(self) -> None:
        """Stop Group replication if enabled on the instance."""
        stop_gr_command = (
            "data = session.run_sql('SELECT 1 FROM performance_schema.replication_group_members')",
            "if len(data.fetch_all()) > 0:",
            "    session.run_sql('STOP GROUP_REPLICATION')",
        )
        try:
            logger.debug("Stopping Group Replication for unit")
            self._run_mysqlsh_script(
                "\n".join(stop_gr_command),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError:
            logger.warning("Failed to stop Group Replication for unit")

    def start_group_replication(self) -> None:
        """Start Group replication on the instance."""
        start_gr_command = "session.run_sql('START GROUP_REPLICATION')"

        try:
            logger.debug("Starting Group Replication for unit")
            self._run_mysqlsh_script(
                start_gr_command,
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError:
            logger.warning("Failed to start Group Replication for unit")

    def reboot_from_complete_outage(self) -> None:
        """Wrapper for reboot_cluster_from_complete_outage command."""
        reboot_from_outage_command = (
            f"dba.reboot_cluster_from_complete_outage('{self.cluster_name}')"
        )

        try:
            self._run_mysqlsh_script(
                reboot_from_outage_command,
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError as e:
            logger.error("Failed to reboot cluster")
            raise MySQLRebootFromCompleteOutageError(e.message)

    def hold_if_recovering(self) -> None:
        """Hold execution if member is recovering."""
        while True:
            try:
                member_state, _ = self.get_member_state()
            except (MySQLNoMemberStateError, MySQLUnableToGetMemberStateError):
                break
            if member_state == MySQLMemberState.RECOVERING:
                logger.debug("Unit is recovering")
                time.sleep(RECOVERY_CHECK_TIME)
            else:
                break

    def set_instance_offline_mode(self, offline_mode: bool = False) -> None:
        """Sets the instance offline_mode."""
        mode = "ON" if offline_mode else "OFF"
        set_instance_offline_mode_commands = (f"SET @@GLOBAL.offline_mode = {mode}",)

        try:
            self._run_mysqlcli_script(
                set_instance_offline_mode_commands,
                user=self.server_config_user,
                password=self.server_config_password,
            )
        except MySQLClientError:
            logger.error(f"Failed to set instance state to offline_mode {mode}")
            raise MySQLSetInstanceOfflineModeError

    def set_instance_option(self, option: str, value: Any) -> None:
        """Sets an instance option."""
        set_instance_option_commands = (
            f"cluster = dba.get_cluster('{self.cluster_name}')",
            f"cluster.set_instance_option('{self.instance_address}', '{option}', '{value}')",
        )

        try:
            self._run_mysqlsh_script(
                "\n".join(set_instance_option_commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError:
            logger.error(f"Failed to set option {option} with value {value}")
            raise MySQLSetInstanceOptionError

    def offline_mode_and_hidden_instance_exists(self) -> bool:
        """Indicates whether an instance exists in offline_mode and hidden from router."""
        offline_mode_message = "Instance has offline_mode enabled"
        commands = (
            f"cluster_topology = dba.get_cluster('{self.cluster_name}').status()['defaultReplicaSet']['topology']",
            f"selected_instances = [label for label, member in cluster_topology.items() if '{offline_mode_message}' in member.get('instanceErrors', '') and member.get('hiddenFromRouter')]",
            "print(f'<OFFLINE_MODE_INSTANCES>{len(selected_instances)}</OFFLINE_MODE_INSTANCES>')",
        )

        try:
            output = self._run_mysqlsh_script(
                "\n".join(commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError:
            logger.error("Failed to query offline mode instances")
            raise MySQLOfflineModeAndHiddenInstanceExistsError

        matches = re.search(r"<OFFLINE_MODE_INSTANCES>(.*)</OFFLINE_MODE_INSTANCES>", output)

        if not matches:
            raise MySQLOfflineModeAndHiddenInstanceExistsError("Failed to parse command output")

        return matches.group(1) != "0"

    def get_innodb_buffer_pool_parameters(
        self, available_memory: int
    ) -> Tuple[int, Optional[int], Optional[int]]:
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
        except Exception:
            logger.error("Failed to compute innodb buffer pool parameters")
            raise MySQLGetAutoTuningParametersError("Error computing buffer pool parameters")

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
        s3_parameters: Dict[str, str],
        xtrabackup_location: str,
        xbcloud_location: str,
        xtrabackup_plugin_dir: str,
        mysqld_socket_file: str,
        tmp_base_directory: str,
        defaults_config_file: str,
        user: Optional[str] = None,
        group: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Executes commands to create a backup with the given args."""
        nproc_command = ["nproc"]
        make_temp_dir_command = f"mktemp --directory {tmp_base_directory}/xtra_backup_XXXX".split()

        try:
            nproc, _ = self._execute_commands(nproc_command)
            tmp_dir, _ = self._execute_commands(make_temp_dir_command, user=user, group=group)
        except MySQLExecError:
            logger.error("Failed to execute commands prior to running backup")
            raise MySQLExecuteBackupCommandsError
        except Exception:
            # Catch all other exceptions to prevent the database being stuck in
            # a bad state due to pre-backup operations
            logger.error("Failed unexpectedly to execute commands prior to running backup")
            raise MySQLExecuteBackupCommandsError

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
        except MySQLExecError:
            logger.error("Failed to execute backup commands")
            raise MySQLExecuteBackupCommandsError
        except Exception:
            # Catch all other exceptions to prevent the database being stuck in
            # a bad state due to pre-backup operations
            logger.error("Failed unexpectedly to execute backup commands")
            raise MySQLExecuteBackupCommandsError

    def delete_temp_backup_directory(
        self,
        tmp_base_directory: str,
        user: Optional[str] = None,
        group: Optional[str] = None,
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
            raise MySQLDeleteTempBackupDirectoryError(e.message)
        except Exception:
            logger.error("Failed to delete temp backup directory")
            raise MySQLDeleteTempBackupDirectoryError

    def retrieve_backup_with_xbcloud(
        self,
        backup_id: str,
        s3_parameters: Dict[str, str],
        temp_restore_directory: str,
        xbcloud_location: str,
        xbstream_location: str,
        user=None,
        group=None,
    ) -> Tuple[str, str, str]:
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
            raise MySQLRetrieveBackupWithXBCloudError(e.message)

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
            raise MySQLRetrieveBackupWithXBCloudError(e.message)
        except Exception:
            logger.error("Failed to retrieve backup")
            raise MySQLRetrieveBackupWithXBCloudError

    def prepare_backup_for_restore(
        self,
        backup_location: str,
        xtrabackup_location: str,
        xtrabackup_plugin_dir: str,
        user=None,
        group=None,
    ) -> Tuple[str, str]:
        """Prepare the backup in the provided dir for restore."""
        try:
            innodb_buffer_pool_size, _, _ = self.get_innodb_buffer_pool_parameters(
                self.get_available_memory()
            )
        except MySQLGetAutoTuningParametersError as e:
            raise MySQLPrepareBackupForRestoreError(e.message)

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
            raise MySQLPrepareBackupForRestoreError(e.message)
        except Exception:
            logger.error("Failed to prepare backup for restore")
            raise MySQLPrepareBackupForRestoreError

    def empty_data_files(
        self,
        mysql_data_directory: str,
        user=None,
        group=None,
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
            raise MySQLEmptyDataDirectoryError(e.message)
        except Exception:
            logger.error("Failed to empty data directory in prep for backup restore")
            raise MySQLEmptyDataDirectoryError

    def restore_backup(
        self,
        backup_location: str,
        xtrabackup_location: str,
        defaults_config_file: str,
        mysql_data_directory: str,
        xtrabackup_plugin_directory: str,
        user=None,
        group=None,
    ) -> Tuple[str, str]:
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
            raise MySQLRestoreBackupError(e.message)
        except Exception:
            logger.error("Failed to restore backup")
            raise MySQLRestoreBackupError

    def delete_temp_restore_directory(
        self,
        temp_restore_directory: str,
        user=None,
        group=None,
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
            raise MySQLDeleteTempRestoreDirectoryError(e.message)

    @abstractmethod
    def _execute_commands(
        self,
        commands: List[str],
        bash: bool = False,
        user: Optional[str] = None,
        group: Optional[str] = None,
        env_extra: Dict = {},
        stream_output: Optional[str] = None,
    ) -> Tuple[str, str]:
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
        enable_commands = (
            f"SET PERSIST ssl_ca='{ca_path}'",
            f"SET PERSIST ssl_key='{key_path}'",
            f"SET PERSIST ssl_cert='{cert_path}'",
            f"SET PERSIST require_secure_transport={'on' if require_tls else 'off'}",
            "ALTER INSTANCE RELOAD TLS",
        )

        try:
            self._run_mysqlcli_script(
                enable_commands,
                user=self.server_config_user,
                password=self.server_config_password,
            )
        except MySQLClientError:
            logger.error("Failed to set custom TLS configuration")
            raise MySQLTLSSetupError("Failed to set custom TLS configuration")

    def kill_unencrypted_sessions(self) -> None:
        """Kill non local, non system open unencrypted connections."""
        kill_connections_command = (
            (
                'processes = session.run_sql("'
                "SELECT processlist_id FROM performance_schema.threads WHERE "
                "connection_type = 'TCP/IP' AND type = 'FOREGROUND';"
                '")'
            ),
            "process_id_list = [id[0] for id in processes.fetch_all()]",
            'for process_id in process_id_list:\n  session.run_sql(f"KILL CONNECTION {process_id}")',
        )

        try:
            self._run_mysqlsh_script(
                "\n".join(kill_connections_command),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError:
            logger.error("Failed to kill external sessions")
            raise MySQLKillSessionError

    def kill_client_sessions(self) -> None:
        """Kill non local, non system open unencrypted connections."""
        kill_connections_command = (
            (
                'processes = session.run_sql("'
                "SELECT processlist_id FROM performance_schema.threads WHERE "
                "type = 'FOREGROUND' and connection_type is not NULL and processlist_id != CONNECTION_ID();"
                '")'
            ),
            "process_id_list = [id[0] for id in processes.fetch_all()]",
            'for process_id in process_id_list:\n  session.run_sql(f"KILL CONNECTION {process_id}")',
        )

        try:
            self._run_mysqlsh_script(
                "\n".join(kill_connections_command),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
        except MySQLClientError:
            logger.error("Failed to kill external sessions")
            raise MySQLKillSessionError

    def check_mysqlsh_connection(self) -> bool:
        """Checks if it is possible to connect to the server with mysqlsh."""
        connect_commands = 'session.run_sql("SELECT 1")'

        try:
            self._run_mysqlsh_script(
                connect_commands,
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
            )
            return True
        except MySQLClientError:
            logger.error("Failed to connect to MySQL with mysqlsh")
            return False

    def get_pid_of_port_3306(self) -> Optional[str]:
        """Retrieves the PID of the process that is bound to port 3306."""
        get_pid_command = ["fuser", "3306/tcp"]

        try:
            stdout, _ = self._execute_commands(get_pid_command)
            return stdout
        except MySQLExecError:
            return None

    def flush_mysql_logs(self, logs_type: Union[MySQLTextLogs, list[MySQLTextLogs]]) -> None:
        """Flushes the specified logs_type logs."""
        flush_logs_commands = [
            'session.run_sql("SET sql_log_bin = 0")',
        ]

        if isinstance(logs_type, list):
            flush_logs_commands.extend([
                f"session.run_sql('FLUSH {log.value}')"
                for log in logs_type
                if log != MySQLTextLogs.AUDIT
            ])
            if MySQLTextLogs.AUDIT in logs_type:
                flush_logs_commands.append("session.run_sql(\"set global audit_log_flush='ON'\")")
        elif logs_type != MySQLTextLogs.AUDIT:
            flush_logs_commands.append(f'session.run_sql("FLUSH {logs_type.value}")')  # type: ignore
        else:
            flush_logs_commands.append("session.run_sql(\"set global audit_log_flush='ON'\")")

        try:
            self._run_mysqlsh_script(
                "\n".join(flush_logs_commands),
                user=self.server_config_user,
                password=self.server_config_password,
                host=self.instance_def(self.server_config_user),
                timeout=50,
                exception_as_warning=True,
            )
        except MySQLClientError:
            logger.warning(f"Failed to flush {logs_type} logs.")

    def get_databases(self) -> set[str]:
        """Return a set with all databases on the server."""
        list_databases_commands = (
            'result = session.run_sql("SHOW DATABASES")',
            "for db in result.fetch_all():\n  print(db[0])",
        )

        output = self._run_mysqlsh_script(
            "\n".join(list_databases_commands),
            user=self.server_config_user,
            password=self.server_config_password,
            host=self.instance_def(self.server_config_user),
        )
        return set(output.split())

    def get_non_system_databases(self) -> set[str]:
        """Return a set with all non system databases on the server."""
        return self.get_databases() - {
            "information_schema",
            "mysql",
            "mysql_innodb_cluster_metadata",
            "performance_schema",
            "sys",
        }

    def strip_off_passwords(self, input_string: Optional[str]) -> str:
        """Strips off passwords from the input string."""
        if not input_string:
            return ""
        stripped_input = input_string
        hidden_pass = "*****"
        for password in self.passwords:
            stripped_input = stripped_input.replace(password, hidden_pass)
        if "IDENTIFIED" in input_string:
            # when failure occurs for password setting (user creation, password rotation)
            pattern = r"(?<=IDENTIFIED BY\ \')[^\']+(?=\')"
            stripped_input = re.sub(pattern, hidden_pass, stripped_input)
        return stripped_input

    def strip_off_passwords_from_exception(self, e: Exception) -> None:
        """Remove password from execution exceptions.

        Checks from known exceptions for password. Known exceptions are:
        * ops.pebble: ExecError
        * subprocess: CalledProcessError, TimeoutExpired
        """
        if hasattr(e, "cmd"):
            for i, v in enumerate(e.cmd):  # type: ignore
                e.cmd[i] = self.strip_off_passwords(v)  # type: ignore
        if hasattr(e, "command"):
            for i, v in enumerate(e.command):  # type: ignore
                e.command[i] = self.strip_off_passwords(v)  # type: ignore

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
    def _run_mysqlsh_script(
        self,
        script: str,
        user: str,
        host: str,
        password: str,
        timeout: Optional[int] = None,
        exception_as_warning: bool = False,
    ) -> str:
        """Execute a MySQL shell script.

        Raises MySQLClientError if script execution fails.

        Args:
            script: Mysqlsh script string
            user: User to invoke the mysqlsh script with
            host: Host to run the script on
            password: Password to invoke the mysqlsh script
            timeout: Optional timeout for script execution
            exception_as_warning: (optional) whether the exception should be treated as warning

        Returns:
            String representing the output of the mysqlsh command
        """
        raise NotImplementedError

    @abstractmethod
    def _run_mysqlcli_script(
        self,
        script: Union[Tuple[Any, ...], List[Any]],
        user: str = "root",
        password: Optional[str] = None,
        timeout: Optional[int] = None,
        exception_as_warning: bool = False,
    ) -> list:
        """Execute a MySQL CLI script.

        Execute SQL script as instance with given user.

        Raises:
            MySQLClientError if script execution fails.
            TimeoutError if script execution times out.

        Args:
            script: raw SQL script string
            user: (optional) user to invoke the mysql cli script with (default is "root")
            password: (optional) password to invoke the mysql cli script with
            timeout: (optional) time before the query should timeout
            exception_as_warning: (optional) whether the exception should be treated as warning
        """
        raise NotImplementedError

    @abstractmethod
    def _file_exists(self, path: str) -> bool:
        """Check if a file exists.

        Args:
            path: Path to the file to check
        """
        raise NotImplementedError
