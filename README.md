# gr-file-recorder

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![CI](https://github.com/MrCry0/gr-file-recorder/actions/workflows/ci.yml/badge.svg)](https://github.com/MrCry0/gr-file-recorder/actions/workflows/ci.yml)

GNU Radio **QT GUI sink block** for convenient, operator-triggered
recording of sample streams into templated file outputs.

A drop-in replacement for `blocks.file_sink` in flowgraphs where an
operator — not a script — decides when to record. Filename templates
support date, incremental counter, input-type extension, and
flowgraph-variable substitution. Auto-stop on duration or file-size
limits. Pure-Python OOT module; no C++ build required.

## Preparation

- GNU Radio **3.10+** with the Python block API and `qtgui` module.
- PyQt5 (supplied by the GNU Radio install on most distros).
- Python **3.9+**.
- Optional: `pytest`, `pytest-qt`, `numpy` for running the test suite.

## Build

This is a pure-Python module. There is nothing to compile. Packaging
is `pyproject.toml` only and the supported package manager is
[`uv`](https://github.com/astral-sh/uv) — not plain `pip`.

## Install

GNU Radio and PyQt5 must already be installed on the host (e.g. via
the distro package `gnuradio` on Debian/Ubuntu). Pick the install
flavour that matches what you intend to do:

### For end-users — system install (Ubuntu / Debian `.deb`)

This is the **recommended** install method for end-users.
`gnuradio-companion` runs generated flowgraphs under the system
Python interpreter (`/usr/bin/python3`), so the block must be
installed into system site-packages and the YAML must land in
`/usr/share/gnuradio/grc/blocks/`.

**Prerequisites — install GNU Radio first:**

```bash
sudo apt install gnuradio
```

**Build the Debian package from the in-tree `debian/` directory:**

```bash
# Install build dependencies
sudo apt install debhelper dh-python pybuild-plugin-pyproject \
                 python3-all python3-setuptools devscripts

# Build the package (one directory above the source tree)
cd gr-file-recorder
dpkg-buildpackage -us -uc -b

# Install the resulting .deb
sudo apt install ../gr-file-recorder_*.deb
```

This drops `file_recorder` into `/usr/lib/python3/dist-packages/` and
`file_recorder_sink.block.yml` into `/usr/share/gnuradio/grc/blocks/`.
After install, the block appears in GRC under category **File Recorder**
with no additional configuration.

The installed package can be removed like any other system package:

```bash
sudo apt remove gr-file-recorder
```

**Non-deb alternative** (no Debian packaging tools needed):

```bash
sudo uv pip install --system .          # /usr/local/{lib,share}/...
```

### For contributors — editable venv install

The dev workflow uses a project-local venv that inherits the host's
GR/PyQt:

```bash
cd gr-file-recorder
uv venv --system-site-packages          # one-time
uv pip install -e '.[dev]'              # runtime + dev extras
export GRC_BLOCKS_PATH="$(pwd)/grc:$GRC_BLOCKS_PATH"
gnuradio-companion examples/file_recorder_demo.grc
```

`GRC_BLOCKS_PATH` is needed because the editable install does not
copy the YAML to the system search path. Generated flowgraphs run
under `/usr/bin/python3`, which **cannot** see venv-installed
packages — so this dev path is for editing/testing the YAML and the
test suite, not for running flowgraphs from the GRC GUI.

After either install the block appears in GRC under the category
**File Recorder** as *File Recorder Sink*.

## Usage

1. In GRC, drop a **File Recorder Sink** block into your flowgraph.
2. Connect any stream source to its input port. Match the block's
   `input_type` and `vlen` to the upstream sample type.
3. Configure the filename template — see the *Template Syntax*
   section in [`docs/gr-file-recorder.md`](docs/gr-file-recorder.md)
   for the full grammar.
4. Choose `button_type` (`push` or `toggle`). Optionally set
   `button_name` to prefix the button text (e.g. "IQ Record") and
   `show_template` to display the resolved filename next to the button.
5. Optionally set `record_duration` (seconds) and/or `max_file_size`
   (bytes) for automatic stop.
6. Run the flowgraph. Click the button to start/stop recording. Use
   the `{type}` token in the template to include the input-type
   suffix (e.g. `recording_{date}_{counter}.{type}` → `.fc32`).

## Documentation

- **[OVERVIEW.md](OVERVIEW.md)** — project pitch, core loop,
  target platform, key constraints, and the Definition of Done.
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — folder structure,
  dependency management, threading model, and communication
  patterns (events vs. interfaces).
- **[SPECS.md](SPECS.md)** — authoritative behaviour contract:
  data models, state machine, API signatures, functional
  requirements `FR-01 … FR-12`, and test matrix.
- **[docs/gr-file-recorder.md](docs/gr-file-recorder.md)** —
  narrative spec with full template-syntax grammar, parameter
  tables, and design rationale.

## Contributing

See **[CONTRIBUTING.md](CONTRIBUTING.md)** for commit rules, PR workflow,
and CI expectations.

## Tests

```bash
uv pip install -e '.[dev]'
uv run pytest
```

The test matrix covers all five sample types, `vlen ∈ {1, 4}`, both
button modes, and auto-stop triggers — see `SPECS.md` §6 for the full
list.

## License

GPL-3.0 — see [`LICENSE`](LICENSE).
