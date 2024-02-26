# Copyright 2023 Canonical Ltd.
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

"""Library containing the implementation of the tls certificates relation for mysql charm.

This library is used by the mysql charm to provide the TLS certificates relation.
It requires the TLS certificates library and the MySQL library.

"""


import base64
import logging
import re
import socket
import typing
from typing import List, Optional, Tuple

import ops
from charms.mysql.v0.mysql import MySQLKillSessionError, MySQLTLSSetupError
from charms.tls_certificates_interface.v2.tls_certificates import (
    CertificateAvailableEvent,
    CertificateExpiringEvent,
    TLSCertificatesRequiresV2,
    generate_csr,
    generate_private_key,
)
from ops.charm import ActionEvent
from ops.framework import Object
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus

from constants import (
    MYSQL_DATA_DIR,
    TLS_RELATION,
    TLS_SSL_CA_FILE,
    TLS_SSL_CERT_FILE,
    TLS_SSL_KEY_FILE,
)

logger = logging.getLogger(__name__)

LIBID = "eb73947deedd4380a3a90d527e0878eb"
LIBAPI = 0
LIBPATCH = 5

SCOPE = "unit"

if typing.TYPE_CHECKING:
    from .mysql import MySQLCharmBase


class MySQLTLS(Object):
    """MySQL TLS Provider class."""

    def __init__(self, charm: "MySQLCharmBase"):
        super().__init__(charm, "certificates")
        self.charm = charm

        self.certs = TLSCertificatesRequiresV2(self.charm, TLS_RELATION)

        self.framework.observe(
            self.charm.on.set_tls_private_key_action,
            self._on_set_tls_private_key,
        )
        self.framework.observe(
            self.charm.on[TLS_RELATION].relation_joined, self._on_tls_relation_joined
        )
        self.framework.observe(
            self.charm.on[TLS_RELATION].relation_broken, self._on_tls_relation_broken
        )

        self.framework.observe(self.certs.on.certificate_available, self._on_certificate_available)
        self.framework.observe(self.certs.on.certificate_expiring, self._on_certificate_expiring)

    # =======================
    #  Event Handlers
    # =======================
    def _on_set_tls_private_key(self, event: ActionEvent) -> None:
        """Action for setting a TLS private key."""
        self._request_certificate(event.params.get("internal-key", None))

    def _on_tls_relation_joined(self, event) -> None:
        """Request certificate when TLS relation joined."""
        if self.charm.unit_peer_data.get("unit-initialized") != "True":
            event.defer()
            return
        self._request_certificate(None)

    def _on_certificate_available(self, event: CertificateAvailableEvent) -> None:
        """Enable TLS when TLS certificate available."""
        if (
            event.certificate_signing_request.strip()
            != self.charm.get_secret(SCOPE, "csr").strip()
        ):
            logger.error("An unknown certificate expiring.")
            return

        if self.charm.unit_peer_data.get("tls") == "enabled":
            logger.debug("TLS is already enabled.")
            return

        state, _ = self.charm._mysql.get_member_state()
        if state != "online":
            logger.debug("Unit not initialized yet, deferring TLS configuration.")
            event.defer()
            return

        self.charm.unit.status = MaintenanceStatus("Setting up TLS")

        self.charm.set_secret(
            SCOPE, "chain", "\n".join(event.chain) if event.chain is not None else None
        )
        self.charm.set_secret(SCOPE, "certificate", event.certificate)
        self.charm.set_secret(SCOPE, "certificate-authority", event.ca)

        self.push_tls_files_to_workload()
        try:
            self.charm._mysql.tls_setup(
                ca_path=f"{MYSQL_DATA_DIR}/{TLS_SSL_CA_FILE}",
                key_path=f"{MYSQL_DATA_DIR}/{TLS_SSL_KEY_FILE}",
                cert_path=f"{MYSQL_DATA_DIR}/{TLS_SSL_CERT_FILE}",
                require_tls=True,
            )

            # kill any unencrypted sessions to force clients to reconnect
            self.charm._mysql.kill_unencrypted_sessions()
        except MySQLTLSSetupError:
            logger.error("Failed to set custom TLS configuration.")
            self.charm.unit.status = BlockedStatus("Failed to set TLS configuration.")
            return
        except MySQLKillSessionError:
            logger.warning("Failed to kill unencrypted sessions.")
        # set tls flag for unit
        self.charm.unit_peer_data.update({"tls": "enabled"})
        self.charm.unit.status = ActiveStatus()

    def _on_certificate_expiring(self, event: CertificateExpiringEvent) -> None:
        """Request the new certificate when old certificate is expiring."""
        if event.certificate != self.charm.get_secret(SCOPE, "certificate"):
            logger.error("An unknown certificate expiring.")
            return

        key = self.charm.get_secret(SCOPE, "key").encode("utf-8")
        old_csr = self.charm.get_secret(SCOPE, "csr").encode("utf-8")
        new_csr = generate_csr(
            private_key=key,
            subject=self.charm.get_unit_hostname(),
            organization=self.charm.app.name,
            sans=self._get_sans(),
        )
        self.certs.request_certificate_renewal(
            old_certificate_signing_request=old_csr,
            new_certificate_signing_request=new_csr,
        )
        self.charm.set_secret(SCOPE, "csr", new_csr.decode("utf-8"))

    def _on_tls_relation_broken(self, _) -> None:
        """Disable TLS when TLS relation broken."""
        try:
            if not ops.jujuversion.JujuVersion.from_environ().has_secrets:
                self.charm.set_secret(SCOPE, "certificate-authority", None)
                self.charm.set_secret(SCOPE, "certificate", None)
                self.charm.set_secret(SCOPE, "chain", None)
        except KeyError:
            # ignore key error for unit teardown
            pass
        try:
            self.charm._mysql.tls_setup()
            self.charm.unit_peer_data.pop("tls")
        except MySQLTLSSetupError:
            logger.error("Failed to restore default TLS configuration.")
            self.charm.unit.status = BlockedStatus("Failed to restore default TLS configuration.")

    # =======================
    #  Helpers
    # =======================
    def _request_certificate(self, param: Optional[str]):
        """Request a certificate to TLS Certificates Operator."""
        if param is None:
            key = generate_private_key()
        else:
            key = self._parse_tls_file(param)

        csr = generate_csr(
            private_key=key,
            subject=self.charm.get_unit_hostname(),
            organization=self.charm.app.name,
            sans=self._get_sans(),
        )

        # store secrets
        self.charm.set_secret(SCOPE, "key", key.decode("utf-8"))
        self.charm.set_secret(SCOPE, "csr", csr.decode("utf-8"))
        # set control flag
        self.charm.unit_peer_data.update({"tls": "requested"})
        if self.charm.model.get_relation(TLS_RELATION):
            self.certs.request_certificate_creation(certificate_signing_request=csr)

    @staticmethod
    def _parse_tls_file(raw_content: str) -> bytes:
        """Parse TLS files from both plain text or base64 format."""
        if re.match(r"(-+(BEGIN|END) [A-Z ]+-+)", raw_content):
            return re.sub(
                r"(-+(BEGIN|END) [A-Z ]+-+)",
                "\n\\1\n",
                raw_content,
            ).encode("utf-8")
        return base64.b64decode(raw_content)

    def _get_sans(self) -> List[str]:
        """Create a list of DNS names for a unit.

        Returns:
            A list representing the hostnames of the unit.
        """
        unit_id = self.charm.unit.name.split("/")[1]
        return [
            f"{self.charm.app.name}-{unit_id}",
            socket.getfqdn(),
            str(self.charm.model.get_binding(self.charm.peers).network.bind_address),
        ]

    def get_tls_content(self) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Retrieve TLS content.

        Return TLS files as required by mysql.

        Returns:
            A tuple of strings with the content of server-key, ca and server-cert
        """
        ca = self.charm.get_secret(SCOPE, "certificate-authority")
        chain = self.charm.get_secret(SCOPE, "chain")
        ca_file = chain or ca

        key = self.charm.get_secret(SCOPE, "key")
        cert = self.charm.get_secret(SCOPE, "certificate")
        return key, ca_file, cert

    def push_tls_files_to_workload(self) -> None:
        """Push TLS files to unit."""
        ssl_key, ssl_ca, ssl_cert = self.get_tls_content()

        if ssl_key:
            self.charm._mysql.write_content_to_file(
                f"{MYSQL_DATA_DIR}/{TLS_SSL_KEY_FILE}", ssl_key, permission=0o400
            )

        if ssl_ca:
            self.charm._mysql.write_content_to_file(
                f"{MYSQL_DATA_DIR}/{TLS_SSL_CA_FILE}", ssl_ca, permission=0o400
            )

        if ssl_cert:
            self.charm._mysql.write_content_to_file(
                f"{MYSQL_DATA_DIR}/{TLS_SSL_CERT_FILE}", ssl_cert, permission=0o400
            )
