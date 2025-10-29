# hack

This directory contains scripts that either generate the data maintained by OTA in this repo or use the data to display information about OpenShift update graph.


* [exposure-length.sh](exposure-length.sh): It lists risk declaration for some or all risks with `fixedIn` available.

* [generate-weekly-report.py](generate-weekly-report.py): It display edges for a particular channel and commit which is useful to edit and publish the internal blog.

* [release-open.sh](release-open.sh): It generates the files `channels/candidate-x.y.yaml` and `build-suggestions/x.y.yaml`. An OTAer runs it and creates a pull request like [cincinnati-graph-data#7239](https://github.com/openshift/cincinnati-graph-data/pull/7239) right after OpenShift repos cut the dev branch for the `x.y` minor release.

* [release-ga.sh](release-ga.sh): It creates the necessary files for a new `x.y` minor release which includes fast, stable and, when appropriate, EUS channel files with required metadata for automation. An OTAer runs it and creates a pull request like [cincinnati-graph-data#6808](https://github.com/openshift/cincinnati-graph-data/pull/6808) when the errata with the new minor release has been shipped.

* [release-stable-minor.sh](release-stable-minor.sh): It stabilizes updates from `x.(y-1)` to `x.y`.  An OTAer runs it after GA with a period of  soaking time and generates a pull request like [cincinnati-graph-data#7037](https://github.com/openshift/cincinnati-graph-data/pull/7037) for a Jira ticket like [OTA-1451](https://issues.redhat.com/browse/OTA-1451).

* [release-end-of-maintenance.sh](release-end-of-maintenance.sh): It removes 4.y from stable channel feeders.  An OTAer runs it after 4.y completes its [Maintenance phase][maintenance], to generate a pull like [cincinnati-graph-data#8183](https://github.com/openshift/cincinnati-graph-data/pull/8183).

* [show-edges.py](show-edges.py): It shows the edges of OpenShift update graph.

* [stabilization-changes.py](stabilization-changes.py): It promotes releases to both [public](../channels/) and [internal](../internal-channels/) channels and deployed on the `OTA-stage` cluster to generate a pull request like [cincinnati-graph-data#7243](https://github.com/openshift/cincinnati-graph-data/pull/7243).

* [util.py](util.py): It contains the common functions used by other Python Scripts.

* [validate-blocked-edges.py](validate-blocked-edges.py): It does basic blocked-edges validation and is executed in CI.

[maintenance]: https://access.redhat.com/support/policy/updates/openshift#maintenancesupport
