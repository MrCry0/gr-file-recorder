# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Oleksandr Suvorov <cryosay@gmail.com>

# Pass the package version at build time:
#   rpmbuild -ba gr-file-recorder.spec --define "pkgversion 0.1.1"
# Falls back to the value below when building locally without a define.
%{!?pkgversion: %global pkgversion 0.1.1}

Name:           gr-file-recorder
Version:        %{pkgversion}
Release:        1%{?dist}
Summary:        GNU Radio QT GUI sink block for templated on-demand recording
License:        GPL-3.0-or-later
URL:            https://github.com/cryosay/gr-file-recorder
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  python3-setuptools >= 64
BuildRequires:  pyproject-rpm-macros

# Runtime: host supplies GNU Radio and PyQt5 (not pip-installable in
# typical Fedora setups).
Requires:       gnuradio >= 3.10
Requires:       python3-qt5

%description
file_recorder_sink is a GNU Radio out-of-tree (OOT) pure-Python block
that provides a toolbar button for operator-driven recording of sample
streams to templated files. A drop-in replacement for blocks.file_sink
in flowgraphs where an operator decides when to record.

Filename templates support date, incremental counter, input-type
extension, and flowgraph-variable substitution. Recording stops
automatically on configurable duration or file-size limits. The block
appears in GRC under the File Recorder category as "File Recorder Sink".

%prep
%autosetup

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files file_recorder

%files -f %{pyproject_files}
%license LICENSE
%doc README.md
%{_datadir}/gnuradio/grc/blocks/file_recorder_sink.block.yml
%{_datadir}/gnuradio/examples/gr-file-recorder/file_recorder_demo.grc

%changelog
* Fri Jun 05 2026 Oleksandr Suvorov <cryosay@gmail.com> - 0.1.1-1
- Initial RPM packaging for Fedora
