# build-suggestions
This directory contains the build suggestions from OTA to ART. ART builds [primary metadata](https://github.com/openshift/cincinnati/blob/master/docs/design/openshift.md#update-image) for each OpenShift release: set the "previous" value with all versions from `x.y` and `x.(y-1)` that are within those ranges. When scraping OpenShift releases, Cincinnati becomes an indirect consumer of the suggestions.

The file `build-suggestions/x.y.yaml` is initialized right after [`x.(y-1)` branching off from dev](https://docs.ci.openshift.org/docs/architecture/branching/) (and ideally should be in place for ART to build the first [pre-release](https://semver.org/spec/v2.0.0.html#spec-item-9) version for `x.y`), by running [release-open.sh](../hack/release-open.sh) and then creating a pull request like [cincinnati-graph-data#7239](https://github.com/openshift/cincinnati-graph-data/pull/7239).

## semantics

The filename `x.y.yaml` denotes that it contains the build suggestions for version `x.y`. For example, `build-suggestions/4.3.yaml`:

```yaml
default: # the architecture of the release for which the suggestions are. The suggestions under it are used if no other keys matches the architecture. It has to contains all the fields below.
  minor_min: 4.2.21 # of the previous minor version, 4.(y-1).z, 4.2.21 is the minimum version to include. This excludes 4.2.(z<21).
  minor_block_list: [] # of the set of releases bounded by minor_min and minor_max, also exclude any 4.(y-1).z in this list.
  minor_max: 4.2.9999 # of the previous minor version, 4.(y-1).z, 4.2.9999 is the maximum version to include. This excludes 4.2.(z>9999). 9999 is a placeholder for "never actually exclude anything", because we will never maintain any 4.y branch long enough to have 10,000 patch releases.
  z_min: 4.3.0 # of the current minor version, 4.y.z, 4.3.0 is the minimum version to include. This excludes pre-releases like ECs and RCs, e.g., 4.3.0-ec.0.
  z_block_list: [] # of the set of releases bounded by z_min and z_max, also exclude any 4.y.z in this list.
  z_max: 4.3.9999 # of the current minor version, 4.y.z, 4.3.9999 is the maximum version to include. This excludes 4.3.(z>9999). 9999 is a placeholder for "never actually exclude anything", because we will never maintain any 4.y branch long enough to have 10,000 patch releases.
s390x: # The suggestions for the architecture s390x. It has to contains all the fields below.
  minor_min: 4.2.21
  minor_max: 4.2.9999
  minor_block_list:
    - 4.2.999
  z_min: 4.3.0
  z_max: 4.3.9999
  z_block_list: []
```