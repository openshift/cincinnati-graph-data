# hack

This directory contains scripts that either generate the data maintained by OTA in this repo or use the data to display information about OpenShift update graph.


* [exposure-length.sh](exposure-length.sh): It lists the duration of risk declaration for some or all risks with `fixedIn` available.

* [generate-weekly-report.py](generate-weekly-report.py): It display edges for a particular channel and commit which is useful to edit and publish the internal blog.

* [release-open.sh](release-open.sh): It generates the files `channels/candidate-x.y.yaml` and `build-suggestions/x.y.yaml`. An OTAer runs it and creates a pull request like [cincinnati-graph-data#7239](https://github.com/openshift/cincinnati-graph-data/pull/7239) right after OpenShift repos cut the dev branch for the `x.y` minor release.

* [release-ga.sh](release-ga.sh): It creates the necessary files for a new `x.y` minor release which includes fast, stable and, when appropriate, EUS channel files with required metadata for automation. An OTAer runs it and creates a pull request like [cincinnati-graph-data#6808](https://github.com/openshift/cincinnati-graph-data/pull/6808) when the errata with the new minor release has been shipped.

* [release-stable-minor.sh](release-stable-minor.sh): It stabilizes updates from `x.(y-1)` to `x.y`.  An OTAer runs it after GA with a period of  soaking time and generates a pull request like [cincinnati-graph-data#7037](https://github.com/openshift/cincinnati-graph-data/pull/7037) for a Jira ticket like [OTA-1451](https://issues.redhat.com/browse/OTA-1451).

* [release-end-of-maintenance.sh](release-end-of-maintenance.sh): It removes 4.y from stable channel feeders.  An OTAer runs it after 4.y completes its [Maintenance phase][maintenance], to generate a pull like [cincinnati-graph-data#8183](https://github.com/openshift/cincinnati-graph-data/pull/8183).

* [show-edges.py](show-edges.py): It shows the edges of OpenShift update graph.

* [check-upgrade-path.py](check-upgrade-path.py): Given a current and target version, it reports whether an upgrade path exists, whether that path is unconditional, and any associated risks with Jira/KCS links. See [check-upgrade-path.py](#check-upgrade-pathpy) below for usage and change details.

* [stabilization-changes.py](stabilization-changes.py): It promotes releases to both [public](../channels/) and [internal](../internal-channels/) channels and deployed on the `OTA-stage` cluster to generate a pull request like [cincinnati-graph-data#7243](https://github.com/openshift/cincinnati-graph-data/pull/7243).

* [util.py](util.py): It contains the common functions used by other Python Scripts.

* [validate-blocked-edges.py](validate-blocked-edges.py): It does basic blocked-edges validation and is executed in CI.

[maintenance]: https://access.redhat.com/support/policy/updates/openshift#maintenancesupport

## check-upgrade-path.py

Checks whether an OpenShift upgrade path exists between two versions and reports associated conditional risks (name, message, and Jira/KCS URL).

Run from the repository root:

```bash
# Cross-minor: no channel required; script discovers and prints channels
./hack/check-upgrade-path.py --prefer latest --from 4.17.52 --to 4.21.22

# Explicit stream (default is stable)
./hack/check-upgrade-path.py --prefer latest --stream stable --from 4.17.52 --to 4.21.22

# Fewest hops (default prefer mode)
./hack/check-upgrade-path.py --from 4.15.50 --to 4.21.24

# Optional: force single-channel evaluation when both versions are in that channel
./hack/check-upgrade-path.py --from 4.18.20 --to 4.19.20 --channel stable-4.19
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--from` | required | Current cluster version |
| `--to` | required | Target cluster version |
| `--stream` | `stable` | Channel stream used to discover `stream-X.Y` graphs (`stable`, `fast`, `candidate`, `eus`, ...) |
| `--prefer` | `shortest` | Intermediate selection policy: `shortest` or `latest` |
| `--channel` | unset | Optional. If both versions are present in this channel, evaluate only there |
| `--cincinnati` | `https://api.openshift.com/api/upgrades_info/graph` | Cincinnati graph endpoint |

A positional `CHANNEL` argument is still accepted for backwards compatibility; the stream is extracted from it when `--stream` is left at the default.

### Behavior

- Loads update edges and conditional risks from Cincinnati.
- Prefers unconditional edges; falls back to conditional edges and reports risks with URLs.
- Same minor: uses `{stream}-{major}.{minor}` automatically.
- Cross-minor: auto-stitches across discovered `{stream}-X.Y` channels and prints **Channels used**.
- Intermediate versions are never hard-coded; they come from graph search.
- Exit code `0` means a path exists; `1` means no path; `2` means invalid arguments.

### Prefer modes

- `shortest` (default): minimizes hops; may land on an earlier z-stream in each minor.
- `latest`: advances one minor at a time and tries the newest reachable z-stream first. If that landing cannot reach the final target (for example `4.20.29` cannot update to `4.21.22`), it backtracks to an older landing that can (for example `4.20.27`).

Example (`--prefer latest --from 4.17.52 --to 4.21.22`):

```text
Channels used: stable-4.18, stable-4.19, stable-4.20, stable-4.21
Joined path: 4.17.52 -> 4.18.45 -> 4.19.35 -> 4.20.27 -> 4.21.22
```

### Changes made

1. Added `hack/check-upgrade-path.py` to answer path-exists / risks / Jira URL for a given `--from` and `--to`.
2. Added cross-minor auto-stitch so multi-minor upgrades do not require manually choosing intermediate versions.
3. Added `--prefer shortest|latest` to choose fewest-hop vs newest-z-stream intermediate policy.
4. Made channel optional: default `--stream stable` discovers and reports the channels used instead of requiring a caller-supplied channel that may not contain both versions.
5. Added backtracking so `latest` does not fail when the newest landing in a minor cannot reach the target; older reachable landings are tried instead.
6. Output now includes mode, prefer policy, stream, channels used, joined path, per-channel segments, and associated risks with links.
