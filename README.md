# Cincinnati Graph Data

[Cincinnati][] is an update protocol designed to facilitate automatic updates.
This repository manages the Cincinnati graph for OpenShift.

## Workflow

The [contributing documentation](CONTRIBUTING.md) covers licencing and the usual Git flow.

### Pull metadata

Update the local metadata file to match the currently-live metadata with:

```console
$ hack/pull
```

### Make local adjustments

By editing [`metadata.json`](metadata.json) to add or remove labels.

### Push metadata

Update the currently-live metadata to match the local metadata file with:

```console
$ hack/push --token="${YOUR_TOKEN}"
```

You can leave `--token` unset for a dry run (the actions the script would take are printed either way, but are only executed if you passed a token).

FIXME: haven't bothered dropping in actual --token support yet.

[Cincinnati]: https://github.com/openshift/cincinnati/
