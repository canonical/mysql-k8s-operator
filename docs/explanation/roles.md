# Roles

```{note}
The following roles are available starting on revision 284
```

There are several definitions of roles in Charmed MySQL K8s:
* Predefined instance-level roles
* Predefined database-level roles

```{seealso}
[](/explanation/users)
```

## MySQL K8s roles
MySQL does not provide any built-in roles for users to get permissions from.

## Charmed MySQL K8s instance-level roles

Charmed MySQL K8s introduces the following instance-level predefined roles:

* `charmed_backup`: used for the `backups` user.
* `charmed_stats`: used for the `monitoring` user.
* `charmed_read`: used to provide data read permissions to all databases.
* `charmed_dml`: used to provide data read / write permissions to all databases.
* `charmed_ddl`: used to provide schema modification permissions to all databases.
* `charmed_dba`: used to provide data, schema, and system configuration permissions to all databases.
 
Currently, `charmed_backup` cannot be requested through the relation as extra user roles.

```text
mysql> SELECT host, user FROM mysql.user;
+-----------+------------------+
| host      | user             |
+-----------+------------------+
| ...       | ...              |
| %         | charmed_backup   |
| %         | charmed_dba      |
| %         | charmed_ddl      |
| %         | charmed_dml      |
| %         | charmed_read     |
| %         | charmed_stats    |
| ...       | ...              |
+-----------+------------------+
```

Additionally, the role `charmed_router` is available to ease the integration with [Charmed MySQL Router](https://charmhub.io/mysql-router).
This role contains all the necessary permissions for a MySQL Router relation user to operate.

## Charmed MySQL K8s database-level roles

Charmed MySQL K8s also introduces database level roles, with permissions tied to each database that's created.
Example for a database named `test`:

```text
mysql> SELECT host, user FROM mysql.user WHERE user LIKE '%_test';
+-----------+------------------+
| host      | user             |
+-----------+------------------+
| %         | charmed_dba_test |
+-----------+------------------+
```

The `charmed_dba_<database>` role contains every data and schema related permission, scoped to the database it references.
