## Juju version

The charm supports both [Juju 2.9 LTS](https://github.com/juju/juju/releases) and [Juju 3.1](https://github.com/juju/juju/releases). Note: Juju 3.1 is supported from the charm revision 92+ only.

The minimum supported Juju versions are:

* 2.9.44+ (due to [missing](https://warthogs.atlassian.net/browse/DPE-2396) pebble `kill-delay` feature + fixes for [K8s scale-down](https://bugs.launchpad.net/juju/+bug/1977582) + [managing storage](https://bugs.launchpad.net/juju/+bug/1971937) issues).
* 3.1.6+ (due to issues with Juju secrets in previous versions, see [#1](https://bugs.launchpad.net/juju/+bug/2029285) and [#2](https://bugs.launchpad.net/juju/+bug/2029282))