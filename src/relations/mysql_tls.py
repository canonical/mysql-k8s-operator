# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of the tls certificates relation."""


import base64
import logging
import re
import socket
from string import Template
from typing import List, Optional, Tuple

from charms.tls_certificates_interface.v1.tls_certificates import (
    CertificateAvailableEvent,
    CertificateExpiringEvent,
    TLSCertificatesRequiresV1,
    generate_csr,
    generate_private_key,
)
from ops.charm import ActionEvent, CharmBase, RelationJoinedEvent
from ops.framework import Object
from ops.model import MaintenanceStatus

from constants import TLS_RELATION, TLS_SSL_CA_FILE, TLS_SSL_CERT_FILE, TLS_SSL_KEY_FILE
from mysqlsh_helpers import MYSQL_DATA_DIR, MYSQLD_CONFIG_DIRECTORY

logger = logging.getLogger(__name__)

SCOPE = "unit"


class MySQLTLS(Object):
    """MySQL TLS Provider class."""

    def __init__(self, charm: CharmBase):
        super().__init__(charm, "certificates")
        self.charm = charm

        self.certs = TLSCertificatesRequiresV1(self.charm, TLS_RELATION)

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

    def _on_tls_relation_joined(self, _) -> None:
        """Request certificate when TLS relation joined."""
        self._request_certificate(None)

    def _on_certificate_available(self, event: CertificateAvailableEvent) -> None:
        """Enable TLS when TLS certificate available."""
        if not self.charm.unit_initialized:
            logger.debug("Wait unit initialise before request certificate.")
            event.defer()
            return

        if (
            event.certificate_signing_request.strip()
            != self.charm.get_secret(SCOPE, "csr").strip()
        ):
            logger.error("An unknown certificate expiring.")
            return

        self.charm.unit.status = MaintenanceStatus("Setting up TLS")

        self.charm.set_secret(
            SCOPE, "chain", "\n".join(event.chain) if event.chain is not None else None
        )
        self.charm.set_secret(SCOPE, "cert", event.certificate)
        self.charm.set_secret(SCOPE, "ca", event.ca)

        self.push_tls_files_to_workload()
        self.create_tls_config_file()

        # set member-state to avoid unwanted health-check actions
        self.charm.unit_peer_data["member-state"] = "waiting"
        # trigger rolling restart
        self.charm.on[self.charm.restart_manager.name].acquire_lock.emit()

    def _on_certificate_expiring(self, event: CertificateExpiringEvent) -> None:
        """Request the new certificate when old certificate is expiring."""
        if event.certificate != self.charm.get_secret(SCOPE, "cert"):
            logger.error("An unknown certificate expiring.")
            return

        key = self.charm.get_secret(SCOPE, "key").encode("utf-8")
        old_csr = self.charm.get_secret(SCOPE, "csr").encode("utf-8")
        new_csr = generate_csr(
            private_key=key,
            subject=self.charm.get_unit_hostname(self.charm.unit.name),
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
        self.charm.set_secret(SCOPE, "ca", None)
        self.charm.set_secret(SCOPE, "cert", None)
        self.charm.set_secret(SCOPE, "chain", None)
        self.remove_tls_config_file()
        # set member-state to avoid unwanted health-check actions
        self.charm.unit_peer_data["member-state"] = "waiting"
        # trigger rolling restart
        self.charm.on[self.charm.restart_manager.name].acquire_lock.emit()

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
            subject=self.charm.get_unit_hostname(self.charm.unit.name),
            organization=self.charm.app.name,
            sans=self._get_sans(),
        )

        # store secrets
        self.charm.set_secret(SCOPE, "key", key.decode("utf-8"))
        self.charm.set_secret(SCOPE, "csr", csr.decode("utf-8"))

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
        ca = self.charm.get_secret(SCOPE, "ca")
        chain = self.charm.get_secret(SCOPE, "chain")
        ca_file = chain or ca

        key = self.charm.get_secret(SCOPE, "key")
        cert = self.charm.get_secret(SCOPE, "cert")
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

    def create_tls_config_file(self) -> None:
        """Render TLS template directly to file.

        Render and write TLS enabling config file from template.
        """
        with open("templates/tls.cnf", "r") as template_file:
            template = Template(template_file.read())
            config_string = template.substitute(
                tls_ssl_ca_file=TLS_SSL_CA_FILE,
                tls_ssl_key_file=TLS_SSL_KEY_FILE,
                tls_ssl_cert_file=TLS_SSL_CERT_FILE,
            )

        self.charm._mysql.write_content_to_file(
            f"{MYSQLD_CONFIG_DIRECTORY}/z-custom-tls.cnf",
            config_string,
            owner="root",
            group="root",
            permission=0o644,
        )

    def remove_tls_config_file(self) -> None:
        """Remove TLS configuration file."""
        self.charm._mysql.remove_file(f"{MYSQLD_CONFIG_DIRECTORY}/z-custom-tls.cnf")
