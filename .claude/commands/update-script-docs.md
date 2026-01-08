---
name: update-script-docs
description: Update documentation about scripts in the [hack](../../hack) folder.
allowed-tools: Bash(find ./hack/ -type file --maxdepth 1 -name '*.sh' -o -name '*.py')
---

You are helping update documentation about scripts in the [hack](../../hack) folder.

## Arguments

Usage: `/update-script-docs $ARGUMENTS`

Parse the arguments to a list of files that are either shell or Python script in the [hack](../../hack) folder. The default $ARGUMENTS are taken from the output of the shell command `find ./hack/ -type file -maxdepth 1 -name '*.sh' -o -name '*.py'`.

Example: `/update-script-docs release-ga.sh`


## Task

* Read each given script and understand its functionality

* Update its documentation in [hack/README.md](../../hack/README.md) if the existing is found. Insert it otherwise.