# hack

This directory contains scripts that either generate the data maintained by OTA in this repo or use the data to display information about OpenShift update graph.


* [exposure-length.sh](../hack/exposure-length.sh): It lists risk declaration for some or all risks with `fixedIn` available.

* [generate-weekly-report.py](../hack/generate-weekly-report.py): It display edges for a particular channel and commit which is useful to edit and publish the internal blog.

* [release-open.sh](../hack/release-open.sh): It generates the files `channels/candidate-x.y.yaml` and `build-suggestions/x.y.yaml`. An OTAer runs it and creates a pull request like [cincinnati-graph-data#7239](https://github.com/openshift/cincinnati-graph-data/pull/7239) right after OpenShift repos cut the dev branch for the `x.y` minor release.

* [release-ga.sh](../hack/release-ga.sh): It creates the necessary files for a new `x.y` minor release which includes fast, stable and, when appropriate, EUS channel files with required metadata for automation. An OTAer runs it and creates a pull request like [cincinnati-graph-data#6808](https://github.com/openshift/cincinnati-graph-data/pull/6808) when the errata with the new minor release has been shipped.

* [release-stable-minor.sh](../hack/release-stable-minor.sh): It stabilizes updates from `x.(y-1)` to `x.y`.  An OTAer runs it after GA with a period of  soaking time and generates a pull request like [cincinnati-graph-data#7037](https://github.com/openshift/cincinnati-graph-data/pull/7037) for a Jira ticket like [OTA-1451](https://issues.redhat.com/browse/OTA-1451).

* [show-edges.py](../hack/show-edges.py): It shows the edges of OpenShift update graph.

* [stabilization-changes.py](../hack/stabilization-changes.py): It promotes releases to various channels and deployed on the `OTA-stage` cluster to generate a pull request like [cincinnati-graph-data#7243](https://github.com/openshift/cincinnati-graph-data/pull/7243).

* [util.py](../hack/util.py): It contains the common functions used by other Python Scripts.

* [validate-blocked-edges.py](../hack/validate-blocked-edges.py): It does basic blocked-edges validation and is executed in CI.
