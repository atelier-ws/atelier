# Rubric Authoring

Rubrics define the safety and quality gates that agents must pass before or after executing a task.

## Creating a Rubric

Rubrics use a simple boolean assertion model:

```yaml
id: rubric_shopify_publish
name: "Shopify Publish Verification"
description: "Ensures products are safely published to the store."
checks:
  product_identity_uses_gid:
    description: "Did the agent use the GID to mutate the product?"
    required: true
  pre_publish_snapshot_exists:
    description: "Was a snapshot taken before mutation?"
    required: true
  write_result_checked:
    description: "Did the agent verify the mutation response?"
    required: true
```

## Integrating with the Runtime

When an agent attempts a task associated with this rubric, Atelier forces the agent to explicitly prove how it satisfied each `required: true` check. If it fails, the execution trace is marked as a failure, and a rescue procedure may be triggered.

## Bundling Rubrics in a Pack

```bash
atelier pack create my-rubric-pack --type rubrics
# Add your .yaml rubric files under my-rubric-pack/rubrics/
atelier pack validate ./my-rubric-pack
atelier pack install ./my-rubric-pack
```

Rubrics are installed and used locally. No external distribution infrastructure is required.
