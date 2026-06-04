# Packaging Refactor: Standard Release Pattern

## Status
- **Goal:** Shift from local-build bundling to a standard release pattern (install script fetches pre-built binary).
- **Workspace:** All packaging work is isolated in the git worktree: `/home/pankaj/Projects/leanchain/atelier-installer`.
- **Strategy:**
    1.  Development: Keep `install.sh`.
    2.  CI/CD: Build, compile (Cython), and package (PyInstaller) binaries.
    3.  Distribution: CI/CD uploads pre-built binaries to release storage (e.g., GH Releases).
    4.  Installer: `install.sh` downloads the correct platform-specific binary.

## Next Steps
- [ ] Refactor `scripts/install.sh` to fetch pre-built binaries instead of building locally.
- [ ] Create CI/CD workflow (`.github/workflows/build.yml`) to handle Cython+PyInstaller compilation and release artifact creation.
- [ ] Cleanup remaining build-related scripts in the main repo.
