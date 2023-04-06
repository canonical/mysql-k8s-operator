# Manage Passwords

This is part of the [Charmed MySQL Tutorial](/t/charmed-mysql-k8s-tutorial-overview/9677). Please refer to this page for more information and the overview of the content.

## Passwords
When we accessed MySQL earlier in this tutorial, we needed to use a password manually. Passwords help to secure our database and are essential for security. Over time it is a good practice to change the password frequently. Here we will go through setting and changing the password for the admin user.

### Retrieve the root password
As previously mentioned, the root password can be retrieved by running the `get-password` action on the Charmed MySQL K8s application:
```shell
juju run-action mysql-k8s/leader get-password --wait
```
Running the command should output:
```yaml
unit-mysql-k8s-0:
  UnitId: mysql-k8s/0
  id: "6"
  results:
    password: sQI3Ojih7uL5UC4J1D9Xuqgx
    username: root
  status: completed
  timing:
    completed: 2023-02-15 21:51:04 +0000 UTC
    enqueued: 2023-02-15 21:50:59 +0000 UTC
    started: 2023-02-15 21:51:04 +0000 UTC
```

### Rotate the root password
You can change the root password to a new random password by entering:
```shell
juju run-action mysql-k8s/leader set-password --wait
```
Running the command should output:
```yaml
unit-mysql-k8s-0:
  UnitId: mysql-k8s/0
  id: "10"
  results: {}
  status: completed
  timing:
    completed: 2023-02-15 21:51:37 +0000 UTC
    enqueued: 2023-02-15 21:51:34 +0000 UTC
    started: 2023-02-15 21:51:37 +0000 UTC
```
Please notice the `status: completed` above which means the password has been successfully updated. To be sure, please call `get-password` once again:
```shell
juju run-action mysql-k8s/leader get-password --wait
```
Running the command should output:
```yaml
unit-mysql-k8s-0:
  UnitId: mysql-k8s/0
  id: "12"
  results:
    password: sN6bcP1j7xRfhw4ZDblcIYK1
    username: root
  status: completed
  timing:
    completed: 2023-02-15 21:52:13 +0000 UTC
    enqueued: 2023-02-15 21:52:11 +0000 UTC
    started: 2023-02-15 21:52:12 +0000 UTC

```
The root password should be different from the previous password.

### Set the root password
You can change the root password to a specific password by entering:
```shell
juju run-action mysql-k8s/leader set-password password=my-password --wait && \
juju run-action mysql-k8s/leader get-password --wait
```
Running the command should output:
```yaml
unit-mysql-k8s-0:
  UnitId: mysql-k8s/0
  id: "16"
  results: {}
  status: completed
  timing:
    completed: 2023-02-15 21:52:47 +0000 UTC
    enqueued: 2023-02-15 21:52:45 +0000 UTC
    started: 2023-02-15 21:52:46 +0000 UTC
unit-mysql-k8s-0:
  UnitId: mysql-k8s/0
  id: "18"
  results:
    password: my-password
    username: root
  status: completed
  timing:
    completed: 2023-02-15 21:52:48 +0000 UTC
    enqueued: 2023-02-15 21:52:47 +0000 UTC
    started: 2023-02-15 21:52:47 +0000 UTC
```
The root `password` should match whatever you passed in when you entered the command.