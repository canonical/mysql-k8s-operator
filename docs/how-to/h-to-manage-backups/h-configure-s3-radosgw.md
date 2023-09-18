Charmed MySQL K8s backup can be stored on any S3 compatible storage, e.g. on [Ceph](https://ceph.com/en/) via [RadosGW](https://docs.ceph.com/en/latest/man/8/radosgw/). The S3 access and configurations are managed with the [s3-integrator charm](https://charmhub.io/s3-integrator). Deploy and configure the s3-integrator charm for **RadosGW** (click [here](/t/charmed-mysql-k8s-how-to-configure-s3-for-aws/9651) to backup on AWS S3):
```shell
# Install MinIO client and create a bucket:
mc config host add dest https://radosgw.mycompany.fqdn <access-key> <secret-key> --api S3v4 --lookup path
mc mb dest/backups-bucket

juju deploy s3-integrator
juju run-action s3-integrator/leader sync-s3-credentials access-key=<access-key> secret-key=<secret-key> --wait
juju config s3-integrator \
    endpoint="https://radosgw.mycompany.fqdn" \
    bucket="backups-bucket" \
    path="/mysql-k8s" \
    region="" \
    s3-api-version="" \
    s3-uri-style="path"
```

To pass these configurations to Charmed MySQL K8s, relate the two applications:
```shell
juju relate s3-integrator mysql-k8s
```

You can create/list/restore backups now:

```shell
juju run-action mysql-k8s/leader list-backups --wait
juju run-action mysql-k8s/leader create-backup --wait
juju run-action mysql-k8s/leader list-backups --wait
juju run-action mysql-k8s/leader restore backup-id=<backup-id-here> --wait
```

You can also update your S3 configuration options after relating, using:
```shell
juju config s3-integrator <option>=<value>
```
The s3-integrator charm [accepts many configurations](https://charmhub.io/s3-integrator/configure) - enter whatever configurations are necessary for your S3 storage.