# About

This repo needs to represent the following information:

1. Adding/removing versions to channels
2. Remove or add edges to all channels
3. Remove or add edges to a specific channel
4. Implement an "upgrade policy" object specifically for y-streams

Remember that Cincinnati should pull most edges from the release manifest. This data should typically remove edges, not add them.

# Directory Structure

We do this via a combination of objects and directory structure. All object should be YAML (so we can make comments). The directories in the repo should be:
- /nodes/
- /channels/
- /added_edges/
- /blocked_edges/
- /y-policies/

# Nodes

The /nodes objects are very simple. It is not strictly necessary as long as Cincinnati pulls all releases from quay. However it is useful for a CI tool to build a final (smaller) graph and for disconnected customers to build a complete Cincinnati graph. (though the later is not the first target goal!) So /nodes/4.1.24 would look like:
```
version: 4.1.24
payload: quay.io/openshift-release-dev/ocp-release@sha256:6f87fb66dfa907db03981e69474ea3069deab66358c18d965f6331bd727ff23f
```

# Channels

The /channels object described the nodes in a channel. For example the /channels/stable-4.1.yaml file would contain

```
name: stable-4.1
versions:
  - 4.1.0
  - 4.1.1
  - ...
  - 4.1.11
  # 4.1.12 Was excluded from stable because it wasn't signed!
  - 4.1.13
  - 4.1.14
subchannels:
```

Subchannels can be implemented later. The idea is that inside stable-4.2.yaml we would have:
```
subchannels:
  - stable-4.1
```
Which would pull all nodes from stable-4.1 into stable-4.2. Without having to explicitly add them.

# Added Edges

Adding edges will be rare. It will have the same format as removed edges. It will typiclly be used only in conjunction with 'policy' below.

# Blocked Edges

Blocked edges will be used any time we find a problem. The blocked edge object for /blocked_edges/4.1.10.yaml would look like:
```
to: 4.1.10
- channels:
    - *
  from: *
```
This could also be represented as
```
to: 4.1.10
- channels:
    - stable-4.1
    - prerelease-4.1
  from: 4.1.9
- channels:
    - stable-4.1
    - prerelease-4.1
  from: 4.1.8
- channels:
    - stable-4.1
    - prerelease-4.1
  from: 4.1.7
......
```

# Y-Policies

Policy is a very OpenShift y-stream specific edge auto-removal during y-stream transitions. We need to build payloads with all possible edges and have those removed while we determine what is safe to give to customers. We would like this 'auto removed' policy to be encoded in this repo. We think that /y-policies/4.3.yaml would look like:
```
- channels:
    - *
  from: 4.2
  to: 4.3
```
This policy means that we should removed all edges in all channels going from 4.2 to 4.3.

The policies for 4.2 would look like:
```
- channels:
    - stable-4.2
  from: 4.1
  to: 4.2
  from_until: 4.1.24
  to_until: 4.2.7
- channels:
    - fast-4.2
    - candidate-4.2
  from: 4.1
  to: 4.2
  from_until: 4.1.21
  to_until: 4.2.2
```
This means that we removed all edges in stable-4.2 where the source of the edge is in 4.1 and the source version is less than 4.1.24. Any edge with a target in 4.2 and the target version is less than 4.2.7 will be removed. We have different removing in fast-4.2 and candidate-4.2. Note that from_until and to_until are optional. If unset it means ALL source versions and target versions.

# Order of operations

The adding and removing of edges should happen in the order of:
1. policy
2. added edges
3. blocked edges
