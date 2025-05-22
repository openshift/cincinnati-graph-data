# internal-channels
This directory contains non-version specific channels while the _public_ version specific channels stays in the [channels](../channels/) directory.
These channels here are only for internal use (and they might become public as well in the future when more support for them is available).

ART determines the releases in [candidate.yaml](candidate.yaml) and OTA promotes them to other channels channels in this folder with [stabilization-changes.py](../hack/stabilization-changes.py).

An OTAer may also modify the files occasionally. E.g., [cincinnati-graph-data#6808](https://github.com/DavidHurta/cincinnati-graph-data/commit/ef503aa2b0589fd808ca35e3aed50c123a920705#diff-9843fccf4355b6cf681933687087a8c876e46b7c326fe14d4a47ffa432ae077aR618).
