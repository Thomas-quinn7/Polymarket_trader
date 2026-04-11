# Contributing to Polymarket Trading Framework

Thank you for your interest in contributing. Please read this guide before submitting any changes.

## License agreement

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0-only)**.

By submitting a contribution (pull request, patch, or otherwise) you agree that:

- Your contribution is your original work and you have the right to submit it.
- Your contribution will be licensed under AGPL-3.0-only, the same license as this project.
- Copyright of the overall project remains with the primary author (Thomas Quinn, github.com/Thomas-quinn7) and co-author (Ciaran McDonnell, github.com/CiaranMcDonnell).

If you are contributing on behalf of an employer or under a contract, ensure you have permission to do so under these terms before submitting.

## What contributions are welcome

- Bug fixes
- Documentation improvements
- New strategy examples (in `strategies/example_strategy/` style)
- Test coverage improvements
- Performance improvements to the core framework

## What will not be accepted

- Changes that remove or alter the `LICENSE`, `NOTICE`, copyright headers, or the framework attribution identifier (`pmf-7e3f-tq343`)
- Changes that introduce dependencies with licenses incompatible with AGPL-3.0
- Features designed to circumvent paper trading safety guards

## How to contribute

1. Fork the repository
2. Create a branch: `git checkout -b fix/your-description`
3. Make your changes and add tests where applicable
4. Ensure the test suite passes: `pytest`
5. Open a pull request against `main` with a clear description of what and why

## Code style

- Python 3.10+ compatible (minimum version required by `@dataclass(slots=True)`)
- Follow the existing patterns in `strategies/example_strategy/` for any strategy work
- Run `black` and `flake8` before submitting

## Reporting issues

Open a GitHub Issue with:
- A clear description of the problem
- Steps to reproduce
- Expected vs actual behaviour
- Relevant log output (sanitise any private keys or credentials before posting)
