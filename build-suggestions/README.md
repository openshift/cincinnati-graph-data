# build-suggestions

This directory contains the build suggestions from the repository maintainers to ART.
ART builds [primary metadata](https://github.com/openshift/cincinnati/blob/master/docs/design/openshift.md#update-image) for each OpenShift release, with the `previous` property listing all versions that are supported sources for updates into that release.
When scraping OpenShift releases, Cincinnati becomes an indirect consumer of the suggestions.

The file `build-suggestions/x.y.yaml` is initialized right after [`x.(y-1)` branchies off from dev](https://docs.ci.openshift.org/docs/architecture/branching/) (and ideally should be in place for ART to build the first [pre-release](https://semver.org/spec/v2.0.0.html#spec-item-9) version for `x.y`), by running [`release-open.sh`](../hack/release-open.sh) and then creating a pull request like [cincinnati-graph-data#7239](https://github.com/openshift/cincinnati-graph-data/pull/7239).

## semantics

The filename `x.y.yaml` contains the build suggestions for version `x.y`. For example, [`build-suggestions/4.22.yaml`](4.22.yaml):

```yaml
min_versions:
- 4.21.6
- 4.22.0
```

says that 4.21.6 and later and 4.22.0 and later should be included as `previous` update sources in future 4.22.z releases.
