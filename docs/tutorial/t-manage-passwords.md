> [Charmed MySQL K8s Tutorial](/t/9677) > 4. Manage passwords

# Manage passwords

When we accessed MySQL earlier in this tutorial, we needed to use a password manually. Passwords help to secure our database and are essential for security. Over time, it is a good practice to change the password frequently. 

This section will go through setting and changing the password for the admin user.

## Summary
* [Retrieve the root password](#retrieve-the-root-password)
* [Rotate the root password](#rotate-the-root-password)
* [Set the root password](#set-the-root-password)

---

## Retrieve the root password
The root user's password can be retrieved by running the `get-password` action on the Charmed MySQL K8s application:
```shell
juju run mysql-k8s/leader get-password
```
Example output:
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

## Rotate the root password
You can change the root user's password to a new random password by running:
```shell
juju run mysql-k8s/leader set-password
```
Example output:
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

The `status: completed` above means the password has been successfully updated. To be sure, call `get-password` once again to check that the root password is different from the previous password.

## Set the root password
You can change the root password to a specific password by running `set-password`:
```shell
juju run mysql-k8s/leader set-password password=my-password
```
Confirm with `get-password`:
```shell
juju run mysql-k8s/leader get-password
```
Example output:
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

> Next step: [5. Integrate with another application](/t/9671)