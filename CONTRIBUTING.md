# Contributing

## Development setup

```bash
git clone https://github.com/cryosay/gr-file-recorder
cd gr-file-recorder
uv venv --system-site-packages   # inherits host GR and PyQt5
uv pip install -e '.[dev]'
```

Prerequisites: GNU Radio 3.10+, PyQt5, and Python 3.9+ must already be
installed on the host (e.g. `sudo apt install gnuradio python3-pyqt5` on
Ubuntu/Debian).

## Running tests

```bash
# Full suite
uv run pytest

# Single test
uv run pytest tests/test_qt_button.py::TestToggleButton::test_click_starts_recording

# Qt tests require a display; set offscreen in headless environments
QT_QPA_PLATFORM=offscreen uv run pytest
```

## Code style

This project uses [ruff](https://docs.astral.sh/ruff/) for linting. Run it
before opening a PR:

```bash
uv run ruff check .
```

Rules enforced: standard pycodestyle errors/warnings (`E`, `W`), pyflakes
(`F`), and import sorting (`I`). Long lines (`E501`) are not enforced.

All new code must target Python 3.9+. Type hints are expected on public
methods. No module-level globals — all state belongs on the block instance.

## Commit format

Every commit message must follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>

<body>

Signed-off-by: Your Name <your@email>
```

**Types:** `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`, `ci`

**Scope:** optional; the affected module or subsystem (e.g. `recorder`,
`grc`, `build`, `ci`).

**Subject rules:**
- Imperative mood: "add", "fix", "remove" — not "added", "fixes"
- 72 characters maximum
- No trailing period

**Body rules:**
- Required on every commit
- Explain *why* the change is needed, not what the diff already shows
- 70 characters per line maximum
- Separated from the subject by one blank line

**Signed-off-by:** every commit must end with this trailer as a certificate
of origin (see [DCO](https://developercertificate.org/)). Use `git commit -s`
to add it automatically.

CI rejects commits that violate these rules. Validate your branch locally
before pushing:

```bash
python3 .github/scripts/check-commits.py main..HEAD
```

## Pull request workflow

1. Fork the repository and create a feature branch on your fork.
2. Make changes in small, atomic commits — one logical change per commit.
   Split production code, tests, and documentation into separate commits
   when the concerns are independent.
3. Ensure the tree builds and all tests pass at every commit, not just the
   last one.
4. Run `uv run pytest` and `uv run ruff check .` before pushing.
5. Open a pull request from your branch to `main`. Describe *why* the
   change is needed in the PR description.
6. CI must be green before review is requested.

## CI overview

Every push and pull request runs:

| Job | What it checks |
|---|---|
| Commit messages | Conventional Commits format and Signed-off-by trailer |
| Lint | `ruff check .` |
| Test / Ubuntu 24.04 | Full pytest suite |
| Test / Fedora 42 | Full pytest suite |
| Package / deb | Builds `gr-file-recorder_*.deb` via `dpkg-buildpackage` |
| Package / rpm | Builds `.noarch.rpm` and `.src.rpm` via `rpmbuild` |

Packages are uploaded as CI artifacts (30-day retention). On a new tag, a
GitHub Release is created automatically with the source archive, `.deb`,
`.noarch.rpm`, and `.src.rpm`.

## Packaging a release

Before tagging, ensure the version is consistent across these three files:

| File | Field |
|---|---|
| `pyproject.toml` | `[project] version` |
| `debian/changelog` | top entry version (e.g. `0.2.0-1`) |
| `gr-file-recorder.spec` | fallback `pkgversion` global |

Then create an annotated tag — the tag annotation becomes the release notes:

```bash
git tag -a v0.2.0 -m "$(cat <<'EOF'
Release 0.2.0

- brief description of what changed
- another item
EOF
)"
git push origin v0.2.0
```

CI will build and publish the release automatically.
