# Releasing to PyPI

Releases are built and published by `.github/workflows/publish.yml` using **PyPI Trusted Publishing** (OIDC), so no
API token is stored in GitHub.

## One-time setup

1. Check the name is free at <https://pypi.org/project/bitsopay/>. If it is taken, change `name` in `pyproject.toml`.
2. On PyPI: *Your projects → Publishing → Add a pending publisher*: owner `Sudharsansm`, repository `Bitsopay`,
   workflow `publish.yml`, environment `pypi`.
3. On GitHub: *Settings → Environments → New environment* named `pypi` (optionally require reviewers).
4. (Optional, recommended) Do the same on <https://test.pypi.org> with environment `testpypi`.
5. Enable *Security → Private vulnerability reporting* so [SECURITY.md](../SECURITY.md) works.

## Each release

1. Move `Unreleased` notes in `CHANGELOG.md` under the new version and date.
2. Bump `__version__` in `src/bitsopay/__init__.py` (single source of truth).
3. `make check && make build` locally; commit and merge to `main`.
4. Tag and publish: `git tag v0.1.1 && git push origin v0.1.1`, then create a GitHub Release from the tag.
   The workflow verifies that the tag matches the package version, runs the full checks, builds, runs `twine check`,
   and uploads to PyPI.

## Manual fallback

```bash
make build
python -m twine upload dist/*     # use an API token; never commit it
```

PyPI versions are immutable: a bad release is *yanked* and superseded, never replaced.
