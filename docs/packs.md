# Configuration Bundles

Atelier supports optional local configuration bundles — collections of domain-specific
ReasonBlocks, rubrics, and failure clusters that you can install into your
local store.

## What a bundle contains

```
my-bundle/
├── blocks/          # .md files (ReasonBlock markdown format)
├── rubrics/         # .yaml files
└── failures/        # .yaml files
```

## Installing a local bundle

```bash
atelier pack install ./path/to/my-bundle
atelier pack list
atelier pack show my-bundle
```

## Creating a bundle

See [docs/authoring/reasonblock-authoring.md](authoring/reasonblock-authoring.md) and
[docs/authoring/rubric-authoring.md](authoring/rubric-authoring.md) for the content formats.

Bundles are **local only**. There is no public registry and no community pack distribution.
