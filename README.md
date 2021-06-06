# Cincinnati Graph Data

[Cincinnati][] is an update protocol designed to facilitate automatic updates.
This repository manages the Cincinnati graph for OpenShift.

## Workflow

The [contributing documentation](CONTRIBUTING.md) covers licencing and the usual Git flow.

1. Create a PR.
1. Merge the PR to master.
1. Update your local master branch.

[Cincinnati][] is configured to track the master branch, so it will automatically react to updates made to this repository.

### Schema Version

The layout of this repository is versioned via [a `version` file](version), which contains the [Semantic Version][semver] of the schema.
As a schema version, the patch level is likely to remain 0, but the minor version will be incremented if backwards-compatible features are added, and the major version will be incremented if backwards-incompatible changes are made.
Consumers, such as [Cincinnati][], who support *x.y.0* may safely consume this repository when the stated major version matches the understood *x* and the stated minor version is less than or equal to the understood *y*.
For example, a consumer that supports 1.3.0 and 2.1.0 could safely consume 1.2.0, 1.3.0, 2.0.0, 2.1.0, etc., but could not safely consume 1.4.0, 2.2.0, 3.0.0, etc.

### Release Names

Release names are used for [adding releases to channels](#add-releases-to-channels) and [blocking edges](#block-edges).
Architecture-agnostic names will apply to all images with that exact name in the `version` property of the `release-metadata` file included in the release image.
Names with [SemVer build metadata][semver-build] will apply only to releases whose exact name in the `version` property matches the release with the build metadata removed and whose referenced [image architecture][image-arch] matches the given build metadata.
For example, 4.2.14 will apply to both the amd64 and s390x release images, since those both have `4.2.14` in `version`.
And 4.2.14+amd64 would only apply to the amd64 release image.

### Add Releases To Channels

Edit the appropriate file in `channels/`.
For example, to add a release to candidate-4.2 you would edit [`channels/candidate-4.2.yaml`](channels/candidate-4.2.yaml).

The file contains a list of versions.
Please keep the versions in order.
And LEAVE COMMENTS if you skip a version.

#### Feeder Channels

Channel semantics, as documented [here][channel-semantics], show nodes and edges being promoted to successive channels as they prove their stability.
For example, a 4.2.z release will appear in `candidate-4.2` first.
Upon proving itself sufficiently stable in the candidate channel, it will be promoted into `fast-4.2`.
Some time after landing in `fast-4.2`, it will appear in `stable-4.2`.

_Note:_ Once we have phased release rollouts, we will drop the fast/stable distinction from this repository and promote to a unified fast/stable channel with a start time and rollout duration.
Until then, we are using fast channels to feed stable channels with a delay, just like candidate channels feed fast channels.

In this repository, the intended promotion flow is reflected by a `feeder` property in the channel declaration.
For example, for [`channels/fast-4.2.yaml`](channels/fast-4.2.yaml):

```yaml
feeder:
  name: candidate-4.2
  delay: P1W
  errata: public
  filter: 4\.[0-9]+\.[0-9]+(.*hotfix.*|\+amd64|-s390x)?
```

which declares the intention that nodes and edges will be considered for promotion into `fast-4.2` after cooking for one week in `candidate-4.2` or the errata becomes public.
The `delay` value is an [ISO 8601][rfc-3339-p13] [duration][iso-8601-durations].
The optional `errata` property only accepts one value, `public`, and the feeder nodes are promoted when `delay` has elapsed or the release errata becomes public, whichever comes first.
The `filter` value excludes `4.2.0-rc.5` and other releases, while allowing for `4.2.0-0.hotfix-2020-09-19-234758` and `4.2.10-s390x` and `4.2.14+amd64`.

This is the expected delay, but it does not mean that promotion will happen at that moment.
For example, it is possible that release architects decide that there is insufficient data for a `fast-4.2` promotion, in which case the promotion can be delated until sufficient data accumulates.

To see recommended feeder promotions, run:

```console
$ hack/stabilization-change.py
```

##### Tombstones

Removing a node from a channel can strand existing clusters with a `VersionNotFound` error.
To avoid that, unstable nodes are left in their existing channels, but should not be promoted to additional channels.
This is reflected through entries in the optional `tombstones` property.
For example, [`channels/candidate-4.2.yaml`](channels/candidate-4.2.yaml) has:

```yaml
tombstones:
- 4.1.18
- 4.1.20
```

declaring that, while 4.1.18 and 4.1.20 are in `candidate-4.2`, they should not be promoted to subsequent channels (in this case, `fast-4.2`).

### Block Edges

Create/edit an appropriate file in `blocked_edges/`.
- `to` is the release which has the existing incoming edges.
- `from` is a regex for the previous release versions.

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
[iso-8601-durations]: https://en.wikipedia.org/wiki/ISO_8601#Durations
[rfc-3339-p13]: https://tools.ietf.org/html/rfc3339#page-13
[semver]: https://semver.org/spec/v2.0.0.html
[semver-build]: https://semver.org/spec/v2.0.0.html#spec-item-10
