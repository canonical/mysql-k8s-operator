# How to integrate with another application

[Integrations](https://juju.is/docs/juju/relation) (formerly “relations”) are connections between two applications with compatible endpoints. These connections simplify the creation and management of users, passwords, and other shared data.

This guide shows how to integrate Charmed MySQL K8s with both charmed and non-charmed applications.

> For developer information about how to integrate your own charmed application with MySQL K8s, see [Development > How to integrate with your charm](/how-to/development/integrate-with-your-charm).


## Integrate with a charmed application

Integrations with charmed applications are supported via the [`mysql_client`](https://github.com/canonical/charm-relation-interfaces/blob/main/interfaces/mysql_client/v0/README.md) interface, and the legacy `mysql` interface.

### Modern `mysql_client` interface

To integrate with a charmed application that supports the `mysql_client` interface, run
```shell
juju integrate mysql-k8s <charm>
```

To remove the integration, run
```shell
juju remove-relation mysql-k8s <charm>
```

### Legacy `mysql` interface
```{caution}
Note that this interface is **deprecated**.
See more information in [Explanation > Legacy charm](/explanation/legacy-charm).
```

To integrate via the legacy interface, run
 ```shell
juju integrate mysql-k8s:mysql <charm>
```

Extended permissions can be requested using `mysql-root` endpoint:
```shell
juju integrate mysql-k8s:mysql-root <charm>
```

## Integrate with a non-charmed application

To integrate with an application outside of Juju, you must use the [`data-integrator` charm](https://charmhub.io/data-integrator) to create the required credentials and endpoints.

Deploy `data-integrator`:
```shell
juju deploy data-integrator --config database-name=<name>
```

Integrate with MySQL:
```shell
juju integrate data-integrator mysql-k8s
```

Use the `get-credentials` action to retrieve credentials from `data-integrator`:
```shell
juju run data-integrator/leader get-credentials
```

## Rotate applications password

To rotate the passwords of users created for related applications, the relation should be removed and related again. That process will generate a new user and password for the application.

```shell
juju remove-relation <charm> mysql-k8s
juju integrate <charm> mysql-k8s
```

### Internal operator user

The operator user is used internally by the Charmed MySQL K8s application. The `set-password` action can be used to rotate its password.

To set a specific password for the `operator` user, run

```shell
juju run mysql-k8s/leader set-password password=<password>
```

To randomly generate a password for the `operator` user, run

```shell
juju run mysql-k8s/leader set-password
```

