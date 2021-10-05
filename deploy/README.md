# Test deployments

For conveniently testing graph-data state against a locally installed [OpenShift Update Service][osus] operator, edit `spec.source.git` in [`2-build-config.yaml`](2-build-config.yaml) to point at your fork, and then:

```console
$ oc apply -f .
```

[osus]: https://catalog.redhat.com/software/operators/detail/5f0f35842991b4207fcdb202
