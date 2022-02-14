#! /usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""An API for running MySQL shell commands."""

import argparse

import mysqlsh

parser = argparse.ArgumentParser()
parser.add_argument("command", choices=("createcluster", "clusterstatus"))


# TODO: Sessions should be secured with some method,
# passwords should be handled differently
def open_session() -> None:
    """Establishes a shell global session."""
    connection_data = {
        "user": "root",
        "password": "C4n0n1c4l",
        "socket": "/var/run/mysqld/mysqld.sock",
    }
    mysqlsh.globals.shell.connect(connection_data)


# TODO: we should pass the name of the cluster
# to all methods that require it
def cluster_status() -> str:
    """Returns the status key of the cluster."""
    cluster = mysqlsh.globals.dba.get_cluster("my_cluster")
    return cluster.status()["defaultReplicaSet"]["status"]


def cluster_status_ok() -> bool:
    """Returns True if the status of the cluster is OK (or similar), False otherwise."""
    if cluster_status() == "OK" or cluster_status() == "OK_NO_TOLERANCE":
        return True
    return False


def create_innodb_cluster():
    """Creates a MySQL InnoDB Cluster."""
    open_session()
    mysqlsh.globals.dba.create_cluster("my_cluster")


# FIXME: add_instance does not work properly
# at the moment. Some Group Replication issue is
# preventing instances to join the cluster
def add_instance() -> None:
    """Adds a MySQL server instance to the cluster."""
    open_session()
    cluster = mysqlsh.globals.dba.get_cluster("my_cluster")
    # TODO: cluster.add_instance() requires a URI, this should
    # be somehow passed by the charm code
    cluster.add_instance()


if __name__ == "__main__":
    args = parser.parse_args()
    if args.command == "createcluster":
        create_innodb_cluster()
    elif args.command == "clusterstatus":
        cluster_status()
