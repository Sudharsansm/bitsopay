# Contributing to Bitsopay

Thanks for helping! Bitsopay is a small, security-sensitive library, so we value focused changes with tests.
By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- **Report a bug** or **request a feature** via [issues](https://github.com/Sudharsansm/Bitsopay/issues) (use the templates).
- **Security problems**: do not file an issue; follow [SECURITY.md](SECURITY.md).
- **Improve docs**: typos, clearer examples and deployment notes are always welcome.
- **Send a pull request**: for anything larger than a small fix, open an issue first so we can agree on the approach.

## Development setup

```bash
git clone https://github.com/<you>/Bitsopay && cd Bitsopay
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pre-commit install        # optional: runs ruff on commit (pip install pre-commit)
```

## Before you open a PR

```bash
make check      # = ruff check + ruff format --check + mypy --strict + pytest (coverage gate 92%)
```

- Add or update **tests** for every behavior change; bug fixes need a test that fails without the fix.
- Keep the package at **one runtime dependency** (`segno`). New dependencies need a strong justification.
- Keep Python **3.9** compatibility (CI runs 3.9 to 3.13).
- Public API changes need docstrings, docs updates and a `CHANGELOG.md` entry under **Unreleased**.
- Never log or return secrets, amounts or UPI IDs on public routes.

## Pull request guidelines

1. Branch from `main`; one logical change per PR.
2. Write a clear description: what, why, and how you tested.
3. Use [Conventional Commits](https://www.conventionalcommits.org/) style subjects (`fix:`, `feat:`, `docs:`, `test:`, `chore:`).
4. CI must be green. A maintainer will review; please respond to feedback and keep the PR up to date.

## Releasing

Maintainers only; see [docs/releasing.md](docs/releasing.md).

## License

Contributions are licensed under the project's [MIT license](LICENSE).
