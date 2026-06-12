# Packaging Refactor: GitHub Releases Distribution

## Goal

Transition from local compilation (PyInstaller/Cython) to a "Standard Release Pattern" where the installer downloads pre-compiled, IP-protected binaries from GitHub Releases.

## Design

- **Artifact Generation:** CI/CD pipeline builds binaries and attaches them to GitHub Releases.
- **Installer Logic:** `scripts/install.sh` updated to:
  1. Detect OS/Architecture.
  2. Fetch the latest release tag from GitHub.
  3. Download corresponding tarball/zip containing pre-compiled `atelier`, `atelier mcp`, etc.
  4. Extract and place in `~/.local/bin` or equivalent.
- **Fallbacks:** Maintain support for `--local` development mode (build from source).

## Next Steps

1. Create `docs/plans/packaging-refactor.md` with detailed design.
2. Draft changes to `scripts/install.sh` for binary fetching.
3. Define CI/CD workflow to generate and publish binaries.
