# Environment Authoring

Atelier Environments define the boundaries and toolsets available to agents when executing specific domains of work. Internal teams can create Environments to encapsulate specialized workflows (e.g., Shopify Admin operations, Kubernetes cluster management).

## Anatomy of an Environment

An Environment is defined in a `yaml` file:

```yaml
id: env_shopify_admin
version: "1.0.0"
description: "Tools and rubrics for managing Shopify product data."
tools:
  - shopify.update_metafield
  - shopify.fetch_product_by_gid
  - shopify.publish_product
rubrics:
  - rubric_shopify_publish
  - rubric_shopify_metafield_sync
```

## Distributing via Packs

Environments are bundled into Packs (`atelier pack create`). Install them locally to grant agents in your team or deployment access to a predefined toolkit and safety gates.

```bash
# Create the pack
atelier pack create my-env-pack --type environments

# Validate it
atelier pack validate ./my-env-pack

# Install it locally
atelier pack install ./my-env-pack
```

Packs are installed from local paths or private internal paths (`private://`). External URLs and public registries are disabled by default.
