# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""File containing constants to be used in the charm."""

PASSWORD_LENGTH = 24
PEER = "database-peers"
CONTAINER_NAME = "mysql"
MYSQLD_LOCATION = "mysqld"
MYSQLD_SAFE_SERVICE = "mysqld_safe"
ROOT_USERNAME = "root"
CLUSTER_ADMIN_USERNAME = "clusteradmin"
SERVER_CONFIG_USERNAME = "serverconfig"
MONITORING_USERNAME = "monitoring"
BACKUPS_USERNAME = "backups"
DB_RELATION_NAME = "database"
LEGACY_MYSQL = "mysql"
LEGACY_MYSQL_ROOT = "mysql-root"
ROOT_PASSWORD_KEY = "root-password"
SERVER_CONFIG_PASSWORD_KEY = "server-config-password"
CLUSTER_ADMIN_PASSWORD_KEY = "cluster-admin-password"
MONITORING_PASSWORD_KEY = "monitoring-password"
BACKUPS_PASSWORD_KEY = "backups-password"
CONTAINER_RESTARTS = "unit-container-restarts"
UNIT_ENDPOINTS_KEY = "unit-endpoints"
TLS_RELATION = "certificates"
TLS_SSL_CA_FILE = "custom-ca.pem"
TLS_SSL_KEY_FILE = "custom-server-key.pem"
TLS_SSL_CERT_FILE = "custom-server-cert.pem"
MYSQL_CLI_LOCATION = "/usr/bin/mysql"
MYSQLSH_LOCATION = "/usr/bin/mysqlsh"
MYSQL_DATA_DIR = "/var/lib/mysql"
MYSQLD_SOCK_FILE = "/var/run/mysqld/mysqld.sock"
MYSQLSH_SCRIPT_FILE = "/tmp/script.py"
MYSQLD_CONFIG_FILE = "/etc/mysql/mysql.conf.d/z-custom.cnf"
MYSQL_LOG_DIR = "/var/log/mysql"
MYSQL_LOG_FILES = [
    f"{MYSQL_LOG_DIR}/error.log",
    f"{MYSQL_LOG_DIR}/audit.log",
    f"{MYSQL_LOG_DIR}/general.log",
]
MYSQL_SYSTEM_USER = "mysql"
MYSQL_SYSTEM_GROUP = "mysql"
CHARMED_MYSQL_XTRABACKUP_LOCATION = "xtrabackup"
CHARMED_MYSQL_XBCLOUD_LOCATION = "xbcloud"
CHARMED_MYSQL_XBSTREAM_LOCATION = "xbstream"
XTRABACKUP_PLUGIN_DIR = "/usr/lib64/xtrabackup/plugin"
MYSQLD_DEFAULTS_CONFIG_FILE = "/etc/mysql/my.cnf"
MYSQLD_EXPORTER_PORT = "9104"
MYSQLD_EXPORTER_SERVICE = "mysqld_exporter"
GR_MAX_MEMBERS = 9
# TODO: should be changed when adopting cos-agent
COS_AGENT_RELATION_NAME = "metrics-endpoint"
COS_LOGGING_RELATION_NAME = "logging"
LOG_ROTATE_CONFIG_FILE = "/etc/logrotate.d/flush_mysql_logs"
ROOT_SYSTEM_USER = "root"
SECRET_KEY_FALLBACKS = {
    "root-password": "root_password",
    "server-config-password": "server_config_password",
    "cluster-admin-password": "cluster_admin_password",
    "monitoring-password": "monitoring_password",
    "backups-password": "backups_password",
    "certificate": "cert",
    "certificate-authority": "ca",
}
TRACING_RELATION_NAME = "tracing"
TRACING_PROTOCOL = "otlp_http"
