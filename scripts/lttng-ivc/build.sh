#!/bin/bash
#
# Copyright (C) 2017 - Jonathan Rajotte-Julien <jonathan.rajotte-julien@efficios.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

set -xu

PYTHON3="python3"
P3_VERSION=$($PYTHON3 -c 'import sys;v = sys.version.split()[0].split("."); print("{}.{}".format(v[0], v[1]))')

# Tox does not support long path venv for whatever reason.
PYENV_HOME=$(mktemp -d)

# Create virtualenv and install necessary packages
virtualenv --system-site-packages -p $PYTHON3 "$PYENV_HOME"

set +ux
. "$PYENV_HOME/bin/activate"
set -ux

pip install --quiet tox

# Hack for path too long in venv wrapper shebang
TOXWORKDIR=$(mktemp -d)
export TOXWORKDIR

cd src/

# Run test suite via tox
tox -v -- --junit-xml="${WORKSPACE}/result.xml"

# Remove base venv
rm -rf "$PYENV_HOME"

# Save
cp -r "$TOXWORKDIR" "${WORKSPACE}/artifacts"
rm -rf "$TOXWORKDIR"

# EOF

