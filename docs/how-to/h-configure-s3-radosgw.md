[note]
**Note**: All commands are written for `juju >= v.3.0`

If you are using an earlier version, check the [Juju 3.0 Release Notes](https://juju.is/docs/juju/roadmap#heading--juju-3-0-0---22-oct-2022).
[/note]

# Configure S3 for RadosGW

A MySQL K8s backup can be stored on any S3-compatible storage. S3 access and configurations are managed with the [s3-integrator charm](https://charmhub.io/s3-integrator).

This guide will teach you how to deploy and configure the s3-integrator charm on Ceph via [RadosGW](https://docs.ceph.com/en/quincy/man/8/radosgw/), send the configuration to a Charmed MySQL K8s application, and update it. 
> For AWS, see the guide [How to configure S3 for AWS](/t/9651)

## Configure s3-integrator
First, install the MinIO client and create a bucket:
```shell
mc config host add dest https://radosgw.mycompany.fqdn <access-key> <secret-key> --api S3v4 --lookup path
mc mb dest/backups-bucket
```
Then, deploy and run the charm:
```shell
juju deploy s3-integrator
juju run s3-integrator/leader sync-s3-credentials access-key=<access-key> secret-key=<secret-key>
```
Lastly, use `juju config` to add your configuration parameters. For example:
```shell
juju config s3-integrator \
    endpoint="https://radosgw.mycompany.fqdn" \
    bucket="backups-bucket" \
    path="/mysql-k8s" \
    region="" \
    s3-api-version="" \
    s3-uri-style="path"
```

## Integrate with Charmed MySQL K8s

To pass these configurations to Charmed MySQL K8s, integrate the two applications:
```shell
juju integrate s3-integrator mysql-k8s
```

You can create, list, and restore backups now:
```shell
juju run mysql-k8s/leader list-backups
juju run mysql-k8s/leader create-backup
juju run mysql-k8s/leader list-backups
juju run mysql-k8s/leader restore backup-id=<backup-id-here>
```

You can also update your S3 configuration options after integrating, using:
```shell
juju config s3-integrator <option>=<value>
```
The s3-integrator charm [accepts many configurations](https://charmhub.io/s3-integrator/configure) - enter whatever configurations are necessary for your S3 storage.

[note]
[MicroCeph](https://github.com/canonical/microceph)** tip: make sure the `region` for `s3-integrator` matches the `"sudo microceph.radosgw-admin zonegroup list"` output (use `region="default"` by default).
[/note]