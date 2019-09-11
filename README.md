# Cincinnati Graph Data

[Cincinnati][] is an update protocol designed to facilitate automatic updates.
This repository manages the Cincinnati graph for OpenShift.

## Workflow

The [contributing documentation](CONTRIBUTING.md) covers licencing and the usual Git flow.

### Publish a new release

Add JSON for a node under the `nodes` directory.
The filename and subdirectory structure doesn't have a tooling impact, but the convention is to use `<major>.<minor>/<full-version>.json` to make it easy to get the history for separate z streams (e.g. `git log nodes/4.1`).

Schema:

* `metadata` (optional object)
    * `url` (optional string): Canonical URI for the release; generally an Errata URI.
* `payload` (required string): The by-digest pullspec for the release [container image][image].
* `version` (required string): The name of the release.
    Currently [a Semantic Versioning 2.0.0][SemVer] string.

For an example, see [`nodes/4.1/4.1.0.json`](nodes/4.1/4.1.0.json).

If you'd rather create the node entry from tooling, you can use:

```console
$ hack/graph-util.py update-node quay.io/openshift-release-dev/ocp-release:4.1.0
```

### Add a release to a channel

Add a symlink to the `nodes` entry from the `channels/<channel>` directory.
For example, [`channels/stable-4.1/4.1.0.json`](channels/stable-4.1/4.1.0.json) is a symlink to [`nodes/4.1/4.1.0.json`](nodes/4.1/4.1.0.json), which promotes the 4.1.0 release to the `stable-4.1` channel.

```console
$ ln -rs nodes/4.1/4.1.0.json channels/stable-4.1/
```

### Add an upgrade edge between releases

Add JSON for an edge under the `edges` directory.
The filename and subdirectory structure doesn't have a tooling impact, but the convention is to use `<to-major>.<to-minor>/<to-version>/<from-version>.json` to make it easy to get the history for separate z streams (e.g. `git log edges/4.1`).

Schema:

* `channels` (required array of strings): Channel names in which the edge exists.
    This can be a single single channel to allow for per-channel metadata such as phased rollout start times.
    It can also be multiple channels if you do not need channel-specific metadata.
* `from` (required string): The release `version` from which the edge originates.
* `to` (required string): The release `version` where the edge terminates.

For an example, see [`edges/4.1/4.1.2/4.1.0.json`](edges/4.1/4.1.2/4.1.0.json).

To create entries for edges baked into a release image's `release-metadata`, use `extract-edges`.
For example, create edges to 4.1.0 with:

```console
$ hack/graph-util.py extract-edges 4.1.0
```

### Publish to Quay labels

The Quay labels currently supported by Cincinnati aren't rich enough for per-channel edge information and similar.
But pushing to Quay labels allows us to start using this repository for managing data now, without waiting for changes in Cincinnati's metadata consumption.
Push to Quay labels with:

```console
$ hack/graph-util.py push-to-quay --token="${YOUR_TOKEN}"
```

You can leave `--token` unset for a dry run (the actions the script would take are printed either way, but are only executed if you passed a token).

[Cincinnati]: https://github.com/openshift/cincinnati/
[image]: https://kubernetes.io/docs/concepts/containers/images/
[SemVer]: https://semver.org/spec/v2.0.0.html
