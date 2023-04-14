# How to manage related applications

## New `mysql_client` interface:

Relations to new applications are supported via the "[mysql_client](https://github.com/canonical/charm-relation-interfaces/blob/main/interfaces/mysql_client/v0/README.md)" interface. To create a relation:

```shell
juju relate mysql-k8s application
```

To remove a relation:

```shell
juju remove-relation mysql-k8s application
```

## Legacy `mysql` interface:

We have also added support for the database legacy relation from the [original version](https://launchpad.net/TODO) of the charm via the `mysql` interface. Please note that these interface is deprecated.

 ```shell
juju relate mysql-k8s:mysql wordpress-k8s
```

Also extended permissions can be requested using `mysql-root` edpoint:
```shell
juju relate mysql-k8s:mysql-root wordpress-k8s
```


## Rotate applications password

To rotate the passwords of users created for related applications, the relation should be removed and related again. That process will generate a new user and password for the application, while retaining the requested database and data.

```shell
juju remove-relation application mysql-k8s
juju add-relation application mysql-k8s
```

### Internal operator user

The operator user is used internally by the Charmed MySQL Operator, the `set-password` action can be used to rotate its password.

* To set a specific password for the operator user

```shell
juju run-action mysql-k8s/leader set-password password=<password> --wait
```

* To randomly generate a password for the operator user

```shell
juju run-action mysql-k8s/leader set-password --wait
```