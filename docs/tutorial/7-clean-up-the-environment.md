# Clean up your environment

In this tutorial we've successfully deployed and accessed MySQL on MicroK8s, added and removed cluster members, added and removed database users, and enabled a layer of security with TLS.

You may now keep your MySQL K8s deployment running and write to the database, or remove it entirely using the steps in this page.

## Stop your virtual machine
If you'd like to keep your environment for later, simply stop your VM with
```shell
multipass stop my-vm
```

## Delete your virtual machine
If you're done with testing and would like to free up resources on your machine, you can remove the VM entirely.

```{caution}
**Warning**: When you remove VM as shown below, you will lose all the data in MySQL and any other applications inside Multipass VM! 

For more information, see the docs for [`multipass delete`](https://multipass.run/docs/delete-command).
```

**Delete your VM and its data** by running
```shell
multipass delete --purge my-vm
```


## Next Steps

- Run [Charmed MySQL VM on VM/IAAS](https://github.com/canonical/mysql-operator).
- Check out our Charmed offerings of [PostgreSQL K8s](https://charmhub.io/postgresql-k8s?channel=14) and [Kafka K8s](https://charmhub.io/kafka-k8s?channel=edge).
- Read about [High Availability Best Practices](https://canonical.com/blog/database-high-availability)
- [Report](https://github.com/canonical/mysql-k8s-operator/issues) any problems you encountered.
- [Give us your feedback](/reference/contacts).
- [Contribute to the code base](https://github.com/canonical/mysql-k8s-operator)

