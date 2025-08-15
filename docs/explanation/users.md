# Users

There are two main types of users in MySQL:

* **Internal users**, used by the charm operator
* **Relation users**, used by related (integrated) applications
  * **Extra user roles** if the default permissions are not enough

## Internal users

The operator uses the following internal database users:

* `root` - the initial/default MySQL user. Used for very initial bootstrap only.
* `clusteradmin` - the user to manage replication in the MySQL InnoDB ClusterSet.
* `serverconfig` - the user that operates MySQL instances.
* `monitoring` - the user for [COS integration](/how-to/monitoring-cos/enable-monitoring).
* `backups` - the user to [perform/list/restore backups](/how-to/back-up-and-restore/create-a-backup).
* `mysql_innodb_cluster_#######` - the [internal recovery users](https://dev.mysql.com/doc/mysql-shell/8.0/en/innodb-cluster-user-accounts.html#mysql-innodb-cluster-users-created) which enable connections between the servers in the cluster. Dedicated user created for each Juju unit/InnoDB Cluster member.
* `mysql_innodb_cs_#######` - the internal recovery user which enable connections between MySQl InnoDB Clusters in ClusterSet. One user is created for entire MySQL ClusterSet.

The full list of internal users is available in charm [source code](https://github.com/canonical/mysql-k8s-operator/blob/main/src/constants.py). 

```{caution}
It is forbidden to use/manage described above users, as they are dedicated to the operator’s logic.

Use the [data-integrator](https://charmhub.io/data-integrator) charm to generate, manage, and remove external credentials.
```

Example of internal `mysql.user` table on a newly installed charm:

```shell
mysql> select Host,User,account_locked from mysql.user;
+-----------+---------------------------------+----------------+
| Host      | User                            | account_locked |
+-----------+---------------------------------+----------------+
| %         | backups                         | N              |
| %         | clusteradmin                    | N              |
| %         | monitoring                      | N              |
| %         | mysql_innodb_cluster_2277159443 | N              |
| %         | serverconfig                    | N              |
| localhost | mysql.infoschema                | Y              |
| localhost | mysql.session                   | Y              |
| localhost | mysql.sys                       | Y              |
| localhost | root                            | N              |
+-----------+---------------------------------+----------------+
10 rows in set (0.00 sec)
```

Passwords for *internal* users can be rotated using the action `set-password` on the juju leader unit.

```{seealso}
[How to manage passwords](/how-to/manage-passwords)
```

## Relation users

The operator created a dedicated user for every application related/integrated with database. The username is composed by the relation ID and truncated uuid for the model, to ensure there is no username clash in cross model relations. Usernames are limited to 32 chars as per [MySQL limit](https://dev.mysql.com/doc/refman/8.0/en/user-names.html).

Relation users are removed on the juju relation/integration removal request. However, database data stays in place and can be reused on re-created relations (using new user credentials):

```shell
mysql> select Host,User,account_locked from mysql.user where User like 'relation%';
+------+----------------------------+----------------+
| Host | User                       | account_locked |
+------+----------------------------+----------------+
| %    | relation-8_99200344b67b4e9 | N              |
| %    | relation-9_99200344b67b4e9 | N              |
+------+----------------------------+----------------+
2 row in set (0.00 sec)
```

The extra user(s) will be created for relation with [mysql-router-k8s](https://charmhub.io/mysql-router-k8s) charm to provide necessary users for applications related via the `mysql-router-k8s` app:

```shell
mysql> select Host,User,account_locked from mysql.user where User like 'mysql_router%';
+------+----------------------------+----------------+
| Host | User                       | account_locked |
+------+----------------------------+----------------+
| %    | mysql_router1_gwa0oy6xnp8l | N              |
+------+----------------------------+----------------+
1 row in set (0.00 sec)
```

To rotate passwords for relation users, remove the relation and re-relate:

```shell
juju remove-relation mysql-k8s myclientapp
juju wait-for application mysql-k8s
juju relate mysql-k8s myclientapp
```

### Admin port user access

The charm mainly uses the `serverconfig` user for internal operations. For connections with this user, a special admin port is used (port `33062`), which enables the charm to operate MySQL even when users connections are saturated.

For further information on the administrative connection, refer to [MySQL docs](https://dev.mysql.com/doc/refman/8.0/en/administrative-connection-interface.html) on the topic.

