# build-suggestions
This directory contains the build suggestions from OTA to ART. ART builds _primary metadata_ for each OpenShift release: set "Previous" value with all versions from `x.y` and `x.y-1` that are within those ranges. When scaping OpenShift releases, Cincinnati becomes an indirect consumer of the suggestions.

The file `build-suggestions/x.y.yaml` is initialized right after OpenShift repos cut the dev branch for `release-x.y` by running [release-open.sh](../hack/release-open.sh) and then creating a pull request like [cincinnati-graph-data#7239](https://github.com/openshift/cincinnati-graph-data/pull/7239).
