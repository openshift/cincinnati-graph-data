# Cincinnati Graph Data

[Cincinnati][] is an update protocol designed to facilitate automatic updates.
This repository manages the Cincinnati graph for OpenShift.

## Workflow

The [contributing documentation](CONTRIBUTING.md) covers licencing and the usual Git flow.

1. Create a PR.
1. Merge the PR to master.
1. Update your local master branch.

[Cincinnati][] is configured to track the master branch, so it will automatically react to updates made to this repository.

### Release names

Release names are used for [adding releases to channels](#add-releases-to-channels) and [blocking edges](#block-edges).
Architecture-agnostic names will apply to all images with that exact name in the `version` property of the `release-metadata` file included in the release image.
Names with [SemVer build metadata][semver-build] will apply only to releases whose exact name in the `version` property matches the release with the build metadata removed and whose referenced [image architecture][image-arch] matches the given build metadata.
For example, 4.2.14 will apply to both the amd64 and s390x release images, since those both have `4.2.14` in `version`.
And 4.2.14+amd64 would only apply to the amd64 release image.

### Add Releases To Channels

Edit the appropriate file in `channels/`.
For example, to add a release to stable-4.2 you would edit `channels/stable-4.2.yaml`.
Channel semantics are documented [here][channel-semantics].

The file contains a list of versions.
Please keep the versions in order.
And LEAVE COMMENTS if you skip a version.

### Block Edges

Create/edit an appropriate file in `blocked_edges/`.
- `to` is the release which has the existing incoming edges.
- `from` is a regex for the previous release versions.
- `clusters` selects cluster flavors for which the edges will be blocked.
    If it is unset, the edges will blocked for all clusters.
    - `telemetry` is a PromQL expression.
        Clusters will have edges blocked if their cluster ID shows up in `max by (_id) $EXPRESSION`.
    - `insights` is evaluated against the cluster's most-recently pushed insights.
        - `path` is the path extracted from the insights tarball.
        - `jq` is a `jq` expression evaluated on the contents of the extracted `path`.
        Clusters will have edges blocked if the `jq` output is `true`.

For example: to block all incoming edges to a release create a file such as `blocked-edges/4.2.11.yaml` containing:
```yaml
to: 4.2.11
from: .*
```

If you wish to block specific edges it might look like:
```yaml
to: 4.2.0-rc.5
from: 4\.1\.(18|20)
```

[channel-semantics]: https://docs.openshift.com/container-platform/4.3/updating/updating-cluster-between-minor.html#understanding-upgrade-channels_updating-cluster-between-minor
[Cincinnati]: https://github.com/openshift/cincinnati/
[image-arch]: https://github.com/opencontainers/image-spec/blame/v1.0.1/config.md#L103
[semver-build]: https://semver.org/spec/v2.0.0.html#spec-item-10
