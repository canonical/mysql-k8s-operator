[note]
**Note**: All commands are written for `juju >= v.3.0`

If you are using an earlier version, check the [Juju 3.0 Release Notes](https://juju.is/docs/juju/roadmap#heading--juju-3-0-0---22-oct-2022).
[/note]

# Configure S3 for AWS

Charmed MySQL K8s backup can be stored on any S3 compatible storage. The S3 access and configurations are managed with the [s3-integrator charm](https://charmhub.io/s3-integrator). Deploy and configure the s3-integrator charm for **[AWS S3](https://aws.amazon.com/s3/)** (click [here](/t/charmed-mysql-how-to-configure-s3-for-radosgw/10319) to backup on Ceph via RadosGW):
```shell
juju deploy s3-integrator
juju run s3-integrator/leader sync-s3-credentials access-key=<access-key-here> secret-key=<secret-key-here>
juju config s3-integrator \
    endpoint="https://s3.amazonaws.com" \
    bucket="mysql-test-bucket-1" \
    path="/mysql-k8s-test" \
    region="us-west-2"
```
[note] 
The amazon S3 endpoint must be specified as `s3.<region>.amazonaws.com ` within the first 24 hours of creating the bucket. For older buckets, the endpoint `s3.amazonaws.com` can be used.

See [this post](https://repost.aws/knowledge-center/s3-http-307-response) for more information. 
[/note]

To pass these configurations to Charmed MySQL, relate the two applications:
```shell
juju integrate s3-integrator mysql-k8s
```

You can create/list/restore backups now:

```shell
juju run mysql-k8s/leader list-backups
juju run mysql-k8s/leader create-backup
juju run mysql-k8s/leader list-backups
juju run mysql-k8s/leader restore backup-id=<backup-id-here>
```

You can also update your S3 configuration options after relating, using:
```shell
juju config s3-integrator <option>=<value>
```

The s3-integrator charm [accepts many configurations](https://charmhub.io/s3-integrator/configure) - enter whatever configurations are necessary for your S3 storage.