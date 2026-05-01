# Failure Cluster Authoring

Atelier's Failure Analyzer groups similar agent errors into "Clusters." When authoring community packs, you can provide pre-defined failure clusters and associated rescue procedures.

## Defining a Failure Cluster

```yaml
id: cluster_react_stale_closure
name: "React Stale Closure on Hooks"
regex_signatures:
  - "Cannot update a component .* while rendering a different component"
  - "Warning: Maximum update depth exceeded"
rescue_block_id: block_react_deps_array
```

## Best Practices

1. **Be specific**: Use tight regex signatures to avoid false positives.
2. **Always link a rescue**: A cluster should always point to a `ReasonBlock` that explains how to fix the issue.
3. **Distribute via local paths**: Add clusters to an internal pack and install it via `atelier pack install ./my-pack` or `private://pack-id` on all target machines.

```bash
atelier pack create my-failure-clusters --type reasonblocks
# Add your cluster .yaml files under my-failure-clusters/reasonblocks/
atelier pack validate ./my-failure-clusters
atelier pack install ./my-failure-clusters
```
