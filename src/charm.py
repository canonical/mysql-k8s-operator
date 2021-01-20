#!/usr/bin/env python3
# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import mysql.connector
import re
import subprocess

from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    WaitingStatus,
)
from ops.framework import StoredState
from repo import KEY

logger = logging.getLogger(__name__)
PEER = "mysql"


class MySQLCharm(CharmBase):
    """Charm to run MySQL on Kubernetes."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self._stored.set_default(mysql_setup={})
        self.image = OCIImageResource(self, "mysql-image")
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

    @property
    def cluster_size(self) -> int:
        """Return the size of the cluster."""
        rel = self.model.get_relation(PEER)
        return len(rel.units) + 1 if rel is not None else 1

    @property
    def hostnames(self) -> list:
        """Return a list of Kubernetes hostnames."""
        return [self._get_unit_hostname(i) for i in range(self.cluster_size)]

    def _on_start(self, event):
        """Initialize MySQL InnoDB cluster.

        This event handler is deferred if initialization of MySQL
        fails. By doing so it is guaranteed that another
        attempt at initialization will be made.
        """
        unit_number = self._get_unit_number_from_unit_name(self.unit.name)
        hostname = self._get_unit_hostname(unit_number)

        if not self._mysql_is_ready(hostname):
            message = "Waiting for MySQL Service in {}".format(hostname)
            self.unit.status = WaitingStatus(message)
            logger.info(message)
            event.defer()
            return

        if self._stored.mysql_setup.get(hostname) is None:
            self._change_mysql_variables(hostname)
            self._create_idcadmin_user_on_host(hostname)
            self._setup_cluster(hostname)
            self._stored.mysql_setup[hostname] = True
            self.unit.status = ActiveStatus("MySQL is up and running!")

    def _on_install(self, event) -> None:
        if not self.unit.is_leader():
            return

        self._install_required_packages()
        self._add_mysql_repo()
        self._install_mysql_shell()

    def _install_required_packages(self) -> None:
        logger.info("Running apt-get update...")
        subprocess.run(
            "DEBIAN_FRONTEND=noninteractive apt-get update", shell=True, check=True
        )
        logger.info("Installing required packages...")
        subprocess.run(
            "apt-get install -y apt-utils mysql-client wget lsb-release gnupg add-apt-key",
            shell=True,
            check=True,
        )

    def _add_mysql_repo(self) -> None:
        logger.debug("Adding mysql repo gpg key")
        with open("/tmp/mysql_pubkey.asc", "w") as file:
            file.write(KEY)

        subprocess.run(
            "gpg --import /tmp/mysql_pubkey.asc",
            capture_output=True,
            shell=True,
            check=True,
        )
        subprocess.run(
            "apt-key add /tmp/mysql_pubkey.asc",
            capture_output=True,
            shell=True,
            check=True,
        )
        subprocess.run("touch /etc/apt/sources.list.d/mysql.list", shell=True, check=True)
        subprocess.run(
            "echo 'deb http://repo.mysql.com/apt/ubuntu/ focal mysql-tools' > \
            /etc/apt/sources.list.d/mysql.list",
            shell=True,
            check=True,
        )

    def _install_mysql_shell(self) -> None:
        logger.info("Running apt-get update...")
        subprocess.run(
            "DEBIAN_FRONTEND=noninteractive apt-get update", shell=True, check=True
        )
        logger.info("Installing mysql-shell...")
        subprocess.run(
            "DEBIAN_FRONTEND=noninteractive apt-get -y install mysql-shell",
            shell=True,
            check=True,
        )

    def _change_mysql_variables(self, hostname) -> None:
        logger.info("Changing mysql global variables in {}".format(hostname))
        unit_number = self._get_unit_number_from_hostname(hostname)
        queries = [
            "SET GLOBAL enforce_gtid_consistency = 'ON';",
            "SET GLOBAL gtid_mode = 'OFF_PERMISSIVE';",
            "SET GLOBAL gtid_mode = 'ON_PERMISSIVE';" "SET GLOBAL gtid_mode = 'ON';",
            "SET GLOBAL server_id = {0};".format(unit_number),
        ]

        for query in queries:
            cnx = self._get_sql_connection_for_host(hostname)
            cur = cnx.cursor()
            cur.execute(query)
            cnx.close()
            logger.info("Executing query: {}".format(query))

    def _create_idcadmin_user_on_host(self, hostname):
        """This method will execute a user creation query for the idcAdmin user."""

        if len(self.model.config["idcAdmin-password"]) == 0:
            message = "idcAdmin-password not provided"
            logger.error(message)
            self.unit.status = BlockedStatus(message)
            return

        logger.info("Creating user idcAdmin in {}".format(hostname))
        query = """
                SET SQL_LOG_BIN=0;
                CREATE USER 'idcAdmin'@'%' IDENTIFIED BY '{}';
                GRANT ALL ON *.* TO 'idcAdmin'@'%' WITH GRANT OPTION;
                """.format(
            self.model.config["idcAdmin-password"]
        )

        cnx = self._get_sql_connection_for_host(hostname)
        cur = cnx.cursor()
        cur.execute(query)
        cnx.close()

    def _setup_cluster(self, hostname) -> None:
        command = "mysqlsh -uidcAdmin -p{0} -h {1} --execute".format(
            self.model.config["idcAdmin-password"], hostname
        )
        mysqlsh_command = "dba.configureInstance('idcAdmin@{0}:3306',{{password:'{1}',\
        interactive:false,restart:false}});".format(
            hostname, self.model.config["idcAdmin-password"]
        )

        cmd = '{0} "{1}"'.format(command, mysqlsh_command)
        logger.info("Executing mysqlsh - dba.configureInstance in {}...".format(hostname))
        subprocess.run(cmd, shell=True, check=True)

    def _on_config_changed(self, _):
        self._configure_pod()

    def _configure_pod(self):
        """Configure the K8s pod spec for MySQL."""
        if not self.unit.is_leader():
            self.unit.status = ActiveStatus()
            return

        spec = self._build_pod_spec()
        if not spec:
            return
        self.model.pod.set_spec(spec)
        self.unit.status = ActiveStatus()

    def _build_pod_spec(self):
        try:
            self.unit.status = WaitingStatus("Fetching image information")
            image_info = self.image.fetch()
        except OCIImageResourceError:
            logging.exception("An error occurred while fetching the image info")
            self.unit.status = BlockedStatus("Error fetching image information")
            return {}

        config = self.model.config
        self.unit.status = WaitingStatus("Assembling pod spec")
        pod_spec = {
            "version": 3,
            "containers": [
                {
                    "name": self.app.name,
                    "imageDetails": image_info,
                    "ports": [{"containerPort": config["port"], "protocol": "TCP"}],
                    "envConfig": {
                        "MYSQL_ROOT_PASSWORD": config["root-password"],
                    },
                }
            ],
        }

        return pod_spec

    def _mysql_is_ready(self, hostname):
        """Check that every unit has mysql running.

        Until we have a good event-driven way of using the Kubernetes
        readiness probe, we will attempt
        """
        try:
            cnx = self._get_sql_connection_for_host(hostname)
            logger.info("MySQL service is ready for {}.".format(hostname))
        except mysql.connector.Error:
            # TODO: Improve exceptions handling
            logger.info("MySQL service is not ready for {}.".format(hostname))
            return False
        else:
            cnx.close()

        return True

    def _get_sql_connection_for_host(self, hostname):
        config = {
            "user": "root",
            "password": self.model.config["root-password"],
            "host": hostname,
            "port": self.model.config["port"],
        }
        return mysql.connector.connect(**config)

    def _get_unit_hostname(self, _id: int) -> str:
        """Construct a DNS name for a MySQL unit."""
        return "{0}-{1}.{0}-endpoints".format(self.model.app.name, _id)

    def _get_unit_number_from_hostname(self, hostname):
        UNIT_RE = re.compile(".+-(?P<unit>[0-9]+).+")
        match = UNIT_RE.match(hostname)

        if match is not None:
            return int(match.group("unit"))
        return None

    def _get_unit_number_from_unit_name(self, unit_name):
        UNIT_RE = re.compile(".+(?P<unit>[0-9]+)")
        match = UNIT_RE.match(unit_name)

        if match is not None:
            return int(match.group("unit"))
        return None


if __name__ == "__main__":
    main(MySQLCharm)
