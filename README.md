# Cincinnati Graph Data

[Cincinnati][] is an update protocol designed to facilitate automatic updates.
This repository manages the Cincinnati graph for OpenShift.

## Workflow

The [contributing documentation](CONTRIBUTING.md) covers licencing and the usual Git flow.

1. Create a PR.
1. Merge the PR to master.
1. Update your local master branch.
1. Update the labels in quay based on master.

**Do Not Ever Update Quay Labels Based On Your Local Development Branch. Only from master!**

### Add Releases To Channels

Edit the appropriate file in `channels/`.
For example, to add a release to stable-4.2 you would edit `channels/stable-4.2.yaml`.

The file contains a list of versions.
Please keep the versions in order.
And LEAVE COMMENTS if you skip a version.

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

### Publish Quay labels

**DO NOT EVER PUSH YOUR LOCAL BRANCH TO QUAY! Only push AFTER changes have merged to master.**

Push to Quay labels with:

```console
$ hack/graph-util.py push-to-quay --token="${YOUR_TOKEN}"
```

You can leave `--token` unset for a dry run (the actions the script would take are printed either way, but are only executed if you passed a token).

[Cincinnati]: https://github.com/openshift/cincinnati/
