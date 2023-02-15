# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""File containing constants to be used in the charm."""

PASSWORD_LENGTH = 24
PEER = "database-peers"
CONTAINER_NAME = "mysql"
MYSQLD_SERVICE = "mysqld"
ROOT_USERNAME = "root"
CLUSTER_ADMIN_USERNAME = "clusteradmin"
SERVER_CONFIG_USERNAME = "serverconfig"
DB_RELATION_NAME = "database"
LEGACY_MYSQL = "mysql"
LEGACY_OSM_MYSQL = "osm-mysql"
ROOT_PASSWORD_KEY = "root-password"
SERVER_CONFIG_PASSWORD_KEY = "server-config-password"
CLUSTER_ADMIN_PASSWORD_KEY = "cluster-admin-password"
REQUIRED_USERNAMES = [ROOT_USERNAME, SERVER_CONFIG_USERNAME, CLUSTER_ADMIN_USERNAME]
CONTAINER_RESTARTS = "unit-container-restarts"
UNIT_ENDPOINTS_KEY = "unit-endpoints"
TLS_RELATION = "certificates"
TLS_SSL_CA_FILE = "custom-ca.pem"
TLS_SSL_KEY_FILE = "custom-server-key.pem"
TLS_SSL_CERT_FILE = "custom-server-cert.pem"
MYSQL_DATA_DIR = "/var/lib/mysql"
MYSQLD_CONFIG_DIRECTORY = "/etc/mysql/conf.d"
MYSQLD_SOCK_FILE = "/var/run/mysqld/mysqld.sock"
MYSQLSH_SCRIPT_FILE = "/tmp/script.py"
MYSQLD_CONFIG_FILE = "/etc/mysql/conf.d/z-custom.cnf"
MYSQL_SYSTEM_USER = "mysql"
S3_INTEGRATOR_RELATION_NAME = "s3-parameters"
