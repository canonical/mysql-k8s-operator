


# Charm Testing reference

There are [a lot of test types](https://en.wikipedia.org/wiki/Software_testing) available and most of them are well applicable for Charmed MySQL K8s. Here is a list prepared by Canonical:

* Smoke test
* Unit tests
* Integration tests
* System test
* Performance test

**:information_source: Note:** below examples are written for Juju 3.x, but Juju 2.9 is [supported](/reference/system-requirements) as well.<br/>Please adopt the `juju run ...` commands as `juju run-action ... --wait` for Juju 2.9.

## Smoke test

[u]Complexity[/u]: trivial<br/>
[u]Speed[/u]: fast<br/>
[u]Goal[/u]: ensure basic functionality works over short amount of time.

[Setup an Juju 3.x environment](/tutorial/1-set-up-the-environment), deploy DB with test application and start "continuous write" test:
```shell
juju add-model smoke-test

juju deploy mysql-k8s --trust --channel 8.0/edge --config profile=testing
juju scale-application mysql-k8s 3 # (optional)

juju deploy mysql-test-app --channel latest/edge
juju relate mysql-test-app mysql-k8s:database

# Make sure random data inserted into DB by test application:
juju run mysql-test-app/leader get-inserted-data

# Start "continuous write" test:
juju run mysql-test-app/leader start-continuous-writes
export password=$(juju run mysql-k8s/leader get-password username=root | yq '.. | select(. | has("password")).password')
watch -n1 -x juju ssh --container mysql mysql-k8s/leader "mysql -h 127.0.0.1 -uroot -p${password} -e \"select count(*) from continuous_writes_database.data\""

# Watch the counter is growing!
```
[u]Expected results[/u]:

* mysql-test-app continuously inserts records in database `continuous_writes_database` table `data`.
* the counters (amount of records in table) are growing on all cluster members

[u]Hints[/u]:
```shell
# Stop "continuous write" test
juju run mysql-test-app/leader stop-continuous-writes

# Truncate "continuous write" table (delete all records from DB)
juju run mysql-test-app/leader clear-continuous-writes
```

## Unit tests

Please check the "[Contributing](https://github.com/canonical/mysql-k8s-operator/blob/main/CONTRIBUTING.md#testing)" guide and follow `tox run -e unit` examples there.

## Integration tests

Please check the "[Contributing](https://github.com/canonical/mysql-k8s-operator/blob/main/CONTRIBUTING.md#testing)" guide and follow `tox run -e integration` examples there.

## System test

Please check/deploy the charm [mysql-bundle](https://charmhub.io/mysql-k8s-bundle) ([Git](https://github.com/canonical/mysql-k8s-bundle)). It deploy and test all the necessary parts at once.

## Performance test
Refer to the [sysbench documentation](https://discourse.charmhub.io/t/charmed-sysbench-documentation-home/13945).

