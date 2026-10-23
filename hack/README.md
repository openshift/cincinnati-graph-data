# hack

This directory contains scripts that either generate the data maintained by OTA in this repo or use the data to display information about OpenShift update graph.


* [exposure-length.sh](exposure-length.sh): It lists the duration of risk declaration for some or all risks with `fixedIn` available.

* [generate-weekly-report.py](generate-weekly-report.py): It display edges for a particular channel and commit which is useful to edit and publish the internal blog.

* [release-open.sh](release-open.sh): It generates the files `channels/candidate-x.y.yaml` and `build-suggestions/x.y.yaml`. An OTAer runs it and creates a pull request like [cincinnati-graph-data#7239](https://github.com/openshift/cincinnati-graph-data/pull/7239) right after OpenShift repos cut the dev branch for the `x.y` minor release.

* [release-ga.sh](release-ga.sh): It creates the necessary files for a new `x.y` minor release which includes fast, stable and, when appropriate, EUS channel files with required metadata for automation. An OTAer runs it and creates a pull request like [cincinnati-graph-data#6808](https://github.com/openshift/cincinnati-graph-data/pull/6808) when the errata with the new minor release has been shipped.

* [release-stable-minor.sh](release-stable-minor.sh): It stabilizes updates from `x.(y-1)` to `x.y`.  An OTAer runs it after GA with a period of  soaking time and generates a pull request like [cincinnati-graph-data#7037](https://github.com/openshift/cincinnati-graph-data/pull/7037) for a Jira ticket like [OTA-1451](https://issues.redhat.com/browse/OTA-1451).

* [release-end-of-maintenance.sh](release-end-of-maintenance.sh): It removes 4.y from stable channel feeders.  An OTAer runs it after 4.y completes its [Maintenance phase][maintenance], to generate a pull like [cincinnati-graph-data#8183](https://github.com/openshift/cincinnati-graph-data/pull/8183).

* [show-edges.py](show-edges.py): It shows the edges of OpenShift update graph.

* [stabilization-changes.py](stabilization-changes.py): It promotes releases to both [public](../channels/) and [internal](../internal-channels/) channels and deployed on the `OTA-stage` cluster to generate a pull request like [cincinnati-graph-data#7243](https://github.com/openshift/cincinnati-graph-data/pull/7243).

  With a GitHub token, each eligible promotion looks for an existing PR from
  the configured push repository and promotion branch to the upstream branch.
  Clean PRs and PRs whose mergeability is still unknown are left alone, without
  repeated failure notifications. A confirmed merge conflict is repaired only
  when the PR was opened by the authenticated bot and contains one commit
  changing only the expected channel file with the expected version addition.
  Existing bot PRs generated with `safe_dump` are supported. Extra commits,
  unrelated edits, closed PRs, and remote branches without an open PR require
  human review; the error includes the PR link when one is available.

  Repair reapplies the addition on the latest fetched upstream commit, retaining
  upstream versions, comments, and channel settings. Historical unsorted version
  lists retain their existing order. It preserves the original
  commit message verbatim and retains its author and author date; the commit
  hash and committer date change. The existing PR title, body, labels, and holds
  are not edited. GitHub and Prow may reevaluate checks and approvals after a
  branch update. The push uses an explicit `--force-with-lease` against the
  inspected head, so a concurrent branch edit cannot be overwritten. A later
  upstream merge may cause another conflict, which can be repaired on a later
  pass. New PRs and successful repairs use the existing notification webhook.

  `--poll SECONDS` waits that many seconds after each pass; without it the
  script runs once. The checked-in OTA deployment manifest specifies
  `--poll=3600`, which means approximately hourly checks plus processing time.
  PR discovery uses remote state and works after a bot restart without local
  promotion branches. Git commits are constructed with a temporary index, so
  authenticated promotion does not switch HEAD or change local channel files.
  Without a token, the release-management scripts retain their local YAML
  generation behavior.

  Run the bot regression suite with:

  ```sh
  PYTHONPATH=hack python3 -m unittest hack/stabilization-changes.py
  ```

  The Git regression tests use local temporary repositories and a fake GitHub
  API boundary; they do not contact GitHub or send notifications. Before
  deploying a bot change, compare the live configuration with the
  [deployment manifest](https://gitlab.cee.redhat.com/ota/autoreport/-/blob/master/manifests/15-stabilization-changes-dc.yaml)
  and [build manifest](https://gitlab.cee.redhat.com/ota/autoreport/-/blob/master/manifests/13-stabilization-changes-bc.yaml).
  The build manifest consumes upstream `master`, but has no Git source-change
  webhook trigger: arrange an image rebuild and verify the deployed source
  revision rather than assuming that merging the change deploys it.

* [util.py](util.py): It contains the common functions used by other Python Scripts.

* [validate-blocked-edges.py](validate-blocked-edges.py): It does basic blocked-edges validation and is executed in CI.

[maintenance]: https://access.redhat.com/support/policy/updates/openshift#maintenancesupport
