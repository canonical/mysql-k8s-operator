# Manage passwords

Charmed MySQL user credentials are managed with Juju's `get-password` and `set-password` actions.

```{seealso}
[](/explanation/users)
```

## Get password

To retrieve user credentials for the `root` user, run the `get-password` action on the leader unit as follows:

```shell
juju run mysql-k8s/leader get-password
```

To retrieve credentials for a different user:

```shell
juju run mysql-k8s/leader get-password username=<username>
```

### Set password

To change the `root` user's password to a new, randomized password:

```shell
juju run mysql-k8s/leader set-password
```

To set a manual password for the `root` user:

```shell
juju run mysql-k8s/leader set-password password=<password>
```

To set a manual password for another user:

```shell
juju run mysql-k8s/leader set-password username=<username> password=<password>
```