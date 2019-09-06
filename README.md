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

### Add a release to a channel

Add a symlink to the `nodes` entry from the `channels/<channel>` directory.
For example, [`channels/stable-4.1/4.1.0.json`](channels/stable-4.1/4.1.0.json) is a symlink to [`nodes/4.1/4.1.0.json`](nodes/4.1/4.1.0.json), which promotes the 4.1.0 release to the `stable-4.1` channel.

[Cincinnati]: https://github.com/openshift/cincinnati/
[image]: https://kubernetes.io/docs/concepts/containers/images/
[SemVer]: https://semver.org/spec/v2.0.0.html
