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
  errata: public
  filter: 4\.[0-9]+\.[0-9]+(.*hotfix.*|\+amd64|-s390x)?
```

which declares the intention that nodes and edges will be considered for promotion from `candidate-4.2` into `fast-4.2` after the errata becomes public.
The optional `errata` property only accepts one value, `public`, and marks a public errata as sufficient, but not necessary, for promoting a feeder node.
The `filter` value excludes `4.2.0-rc.5` and other releases, while allowing for `4.2.0-0.hotfix-2020-09-19-234758` and `4.2.10-s390x` and `4.2.14+amd64`.

Another example is [`channels/stable-4.2.yaml`](channels/stable-4.2.yaml):

```yaml
feeder:
  name: fast-4.2
  delay: PT48H
```

which declares the intention that nodes and edges will be considered for promotion from `fast-4.2` into `stable-4.2` after a delay of 48 hours.
The `delay` value is an [ISO 8601][rfc-3339-p13] [duration][iso-8601-durations], and spending sufficient time in the feeder channel is sufficient, but not necessary, for promoting the feeder node.

If both `errata` and `delay` are set, the feeder nodes will be promoted when `delay` has elapsed or the release errata becomes public, whichever comes first.

To see recommended feeder promotions, run:

```console
$ hack/stabilization-change.py
```

##### Promoting edges from previous minor to latest minor version in stable channel

To promote edges from the previous minor version to the latest minor version in the stable channel, run the following script at least 3 times when it is time and then send the pull request.

```console
$ hack/release-stable-minor.sh
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

* `to` (required, [string][json-string]) is the release which has the existing incoming edges.
* `from` (required, [string][json-string]) is a regex for the previous release versions.
    If you want to require `from` to match the full version string (and not just a substring), you must include explicit `^` and `$` anchors.
    Release version strings will receive [the architecture-suffix](#release-names) before being compared to this regular expression.
* `url` (optional, [string][json-string]), with a URI documenting the blocking reason.
    For example, this could link to a bug's impact statement or knowledge-base article.
* `name` (optional, [string][json-string]), with a CamelCase reason suitable for [a `ClusterOperatorStatusCondition` `reason` property][api-reason].
* `fixedIn` (optional, [string][json-string]), with the update-target release where the exposure was fixed, either directly, or because that target is newer than the 4.(y-1).z release where the exposure was fixed.
    This feeds risk-extension guards that require either a `fixedIn` declaration or an extension of unfixed risks to later releases to avoid shipping a release that is still exposed to a risk without declaring that risk.
* `message` (optional, [string][json-string]), with a human-oriented message describing the blocking reason, suitable for [a `ClusterOperatorStatusCondition` `message` property][api-message].
* `matchingRules` (optional, [array][json-array]), defining conditions for deciding which clusters have the update recommended and which do not.
    The array is ordered by decreasing precedence.
    Consumers should walk the array in order.
    For a given entry, if a condition type is unrecognized, or fails to evaluate, consumers should proceed to the next entry.
    If a condition successfully evaluates (either as a match or as an explicit does-not-match), that result is used, and no further entries should be attempted.
    If no condition can be successfully evaluated, the update should not be recommended.
    Each entry must be an [object][json-object] with at least the following property:

    * `type` (required, [string][json-string]), defining the type in [the condition type registry][cluster-condition-type-registry].
        For example, `type: PromQL` identifies the condition as [the `PromQL` type][cluster-condition-type-registry-promql].

    Additional properties for each entry are defined in [the cluster-condition type registry][cluster-condition-type-registry].

For example: to block all incoming edges to a release create a file such as `blocked-edges/4.2.11.yaml` containing:

```yaml
to: 4.2.11
from: .*
```

If you wish to block specific edges it might look like:

```yaml
to: 4.2.0-rc.5
from: ^4\.1\.(18|20)[+].*$
```

The `[+].*` portion absorbs [the architecture-suffix](#release-names) from the release name that consumers will use for comparisons.

[api-message]: https://github.com/openshift/api/blob/67c28690af52a69e0b8fa565916fe1b9b7f52f10/config/v1/types_cluster_operator.go#L135-L139
[api-reason]: https://github.com/openshift/api/blob/67c28690af52a69e0b8fa565916fe1b9b7f52f10/config/v1/types_cluster_operator.go#L131-L133
[channel-semantics]: https://docs.openshift.com/container-platform/4.3/updating/updating-cluster-between-minor.html#understanding-upgrade-channels_updating-cluster-between-minor
[Cincinnati]: https://github.com/openshift/cincinnati/
[cluster-condition-type-registry]: https://github.com/openshift/enhancements/blob/master/enhancements/update/targeted-update-edge-blocking.md#cluster-condition-type-registry
[cluster-condition-type-registry-promql]: https://github.com/openshift/enhancements/blob/master/enhancements/update/targeted-update-edge-blocking.md#promql
[image-arch]: https://github.com/opencontainers/image-spec/blame/v1.0.1/config.md#L103
[iso-8601-durations]: https://en.wikipedia.org/wiki/ISO_8601#Durations
[json-array]: https://datatracker.ietf.org/doc/html/rfc8259#section-5
[json-object]: https://datatracker.ietf.org/doc/html/rfc8259#section-4
[json-string]: https://datatracker.ietf.org/doc/html/rfc8259#section-7
[rfc-3339-p13]: https://tools.ietf.org/html/rfc3339#page-13
[semver]: https://semver.org/spec/v2.0.0.html
[semver-build]: https://semver.org/spec/v2.0.0.html#spec-item-10
