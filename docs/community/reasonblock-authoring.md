# ReasonBlock Authoring

ReasonBlocks are the core procedural memory unit in Atelier. They capture lessons learned from past failures or explicit organizational guidelines.

## Structure of a ReasonBlock

A ReasonBlock is typically authored as Markdown with frontmatter:

```markdown
---
id: block_shopify_gid
domains:
  - Agent.shopify.publish
  - Agent.shopify.sync
tags: [shopify, data-model]
priority: high
---

# Use Product GID instead of Handles

When updating product data in Shopify, **never rely on the handle**. Handles can change if the SEO title changes. Always fetch the product by its GID first.

## Correct Procedure

1. Search products by SKU or handle to retrieve the GID.
2. Use the GID for all subsequent mutations.
3. Verify the update via a post-publish fetch using the GID.
```

## Bundling Blocks in a Pack

Bundle ReasonBlocks into domain-specific packs for your team or customer deployment:

```bash
atelier pack create my-reasoning-pack --type reasonblocks
# Add your .md block files under my-reasoning-pack/reasonblocks/
atelier pack validate ./my-reasoning-pack
atelier pack install ./my-reasoning-pack
```

Agents using Atelier will automatically retrieve these blocks when working on matching tasks. Install from local paths; external registries are not used.
