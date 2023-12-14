#!/bin/bash
#
# SPDX-FileCopyrightText: 2015 Jonathan Rajotte-Julien <jonathan.rajotte-julien@efficios.com>
# SPDX-FileCopyrightText: 2023 Michael Jeanson <mjeanson@efficios.com>
# SPDX-License-Identifier: GPL-2.0-or-later

set -exu

# Required variables
WORKSPACE=${WORKSPACE:-}

# Coverity settings
# The project name and token have to be provided trough env variables
#COVERITY_SCAN_PROJECT_NAME=""
#COVERITY_SCAN_TOKEN=""
COVERITY_SCAN_DESCRIPTION="Automated CI build"
COVERITY_SCAN_NOTIFICATION_EMAIL="ci-notification@lists.lttng.org"
COVERITY_SCAN_BUILD_OPTIONS=""
#COVERITY_SCAN_BUILD_OPTIONS=("--return-emit-failures 8" "--parse-error-threshold 85")

DEPS_INC="$WORKSPACE/deps/build/include"
DEPS_LIB="$WORKSPACE/deps/build/lib"
DEPS_PKGCONFIG="$DEPS_LIB/pkgconfig"
DEPS_BIN="$WORKSPACE/deps/build/bin"

export PATH="$DEPS_BIN:$PATH"
export LD_LIBRARY_PATH="$DEPS_LIB:${LD_LIBRARY_PATH:-}"
export PKG_CONFIG_PATH="$DEPS_PKGCONFIG"
export CPPFLAGS="-I$DEPS_INC"
export LDFLAGS="-L$DEPS_LIB"

SRCDIR="$WORKSPACE/src/${COVERITY_SCAN_PROJECT_NAME}"
TMPDIR="$WORKSPACE/tmp"

NPROC=$(nproc)
PLATFORM=$(uname)
export CFLAGS="-O0 -g"
export CXXFLAGS="-O0 -g"

# Cache the tool installer in the home directory since we delete the workspace
# on each build
TOOL_ARCHIVE="$HOME/cov-analysis-${PLATFORM}.tgz"
TOOL_URL=https://scan.coverity.com/download/${PLATFORM}
TOOL_BASE="$TMPDIR/coverity-scan-analysis"

UPLOAD_URL="https://scan.coverity.com/builds"
SCAN_URL="https://scan.coverity.com"

RESULTS_DIR_NAME="cov-int"
RESULTS_DIR="$WORKSPACE/$RESULTS_DIR_NAME"
RESULTS_ARCHIVE=analysis-results.tgz

# Create tmp directory
rm -rf "$TMPDIR"
mkdir -p "$TMPDIR"

export TMPDIR

case "$COVERITY_SCAN_PROJECT_NAME" in
babeltrace)
    CONF_OPTS=("--enable-python-bindings" "--enable-python-bindings-doc" "--enable-python-plugins")
    BUILD_TYPE="autotools"
    ;;
liburcu)
    CONF_OPTS=()
    BUILD_TYPE="autotools"
    ;;
lttng-modules)
    CONF_OPTS=()
    BUILD_TYPE="autotools"
    ;;
lttng-tools)
    CONF_OPTS=()
    BUILD_TYPE="autotools"
    ;;
lttng-ust)
    CONF_OPTS=("--enable-java-agent-all" "--enable-python-agent")
    BUILD_TYPE="autotools"
    export CLASSPATH="/usr/share/java/log4j-api.jar:/usr/share/java/log4j-core.jar:/usr/share/java/log4j-1.2.jar"
    ;;
*)
    echo "Generic project, no configure options."
    CONF_OPTS=()
    BUILD_TYPE="autotools"
    ;;
esac

if [ -d "$WORKSPACE/src/linux" ]; then
	export KERNELDIR="$WORKSPACE/src/linux"
fi

# Enter the source directory
cd "$SRCDIR"

# Verify upload is permitted
set +x
AUTH_RES=$(curl --silent --form project="$COVERITY_SCAN_PROJECT_NAME" --form token="$COVERITY_SCAN_TOKEN" $SCAN_URL/api/upload_permitted)
set -x
if [ "$AUTH_RES" = "Access denied" ]; then
  echo -e "\033[33;1mCoverity Scan API access denied. Check COVERITY_SCAN_PROJECT_NAME and COVERITY_SCAN_TOKEN.\033[0m"
  exit 1
else
  AUTH=$(echo "$AUTH_RES" | jq .upload_permitted)
  if [ "$AUTH" = "true" ]; then
    echo -e "\033[33;1mCoverity Scan analysis authorized per quota.\033[0m"
  else
    WHEN=$(echo "$AUTH_RES" | jq .next_upload_permitted_at)
    echo -e "\033[33;1mCoverity Scan analysis NOT authorized until $WHEN.\033[0m"
    exit 1
  fi
fi


# Download Coverity Scan Analysis Tool
if [ ! -d "$TOOL_BASE" ]; then
  echo -e "\033[33;1mDownloading Coverity Scan Analysis Tool...\033[0m"
  set +x
  curl --fail \
       --location \
       --remote-time \
       --form project="$COVERITY_SCAN_PROJECT_NAME" \
       --form token="$COVERITY_SCAN_TOKEN" \
       --output "$TOOL_ARCHIVE" \
       "$TOOL_URL" || rm -f "$TOOL_ARCHIVE"
  set -x

  # Extract Coverity Scan Analysis Tool
  echo -e "\033[33;1mExtracting Coverity Scan Analysis Tool...\033[0m"
  mkdir -p "$TOOL_BASE"
  cd "$TOOL_BASE" || exit 1
  tar xzf "$TOOL_ARCHIVE"
  cd -
fi

TOOL_DIR=$(find "$TOOL_BASE" -type d -name 'cov-analysis*')
export PATH=$TOOL_DIR/bin:$PATH

COVERITY_SCAN_VERSION=$(git describe --always | sed 's|-|.|g')

# Build
echo -e "\033[33;1mRunning Coverity Scan Analysis Tool...\033[0m"
case "$BUILD_TYPE" in
maven)
    cov-configure --java
    cov-build --dir "$RESULTS_DIR" "${COVERITY_SCAN_BUILD_OPTIONS[@]}" "$MVN_BIN" \
      -s "$MVN_SETTINGS" \
      -Dmaven.repo.local="$WORKSPACE/.repository" \
      -Dmaven.compiler.fork=true \
      -Dmaven.compiler.forceJavaCompilerUse=true \
      -Dmaven.test.skip=true \
      -DskipTests \
      clean verify
    ;;
autotools)
    # Prepare build dir for autotools based projects
    if [ -f "./bootstrap" ]; then
      ./bootstrap
      ./configure "${CONF_OPTS[@]}"
    fi

    cov-build --dir "$RESULTS_DIR" ${COVERITY_SCAN_BUILD_OPTIONS[@]} make -j"$NPROC" V=1
    ;;
*)
    echo "Unsupported build type: $BUILD_TYPE"
    exit 1
    ;;
esac



cov-import-scm --dir "$RESULTS_DIR" --scm git --log "$RESULTS_DIR/scm_log.txt"

cd "${WORKSPACE}"

# Tar results
echo -e "\033[33;1mTarring Coverity Scan Analysis results...\033[0m"
tar czf $RESULTS_ARCHIVE $RESULTS_DIR_NAME

# Upload results
echo -e "\033[33;1mUploading Coverity Scan Analysis results...\033[0m"
response=$(curl \
  --write-out "\n%{http_code}\n" \
  --form project="$COVERITY_SCAN_PROJECT_NAME" \
  --form token="$COVERITY_SCAN_TOKEN" \
  --form email="$COVERITY_SCAN_NOTIFICATION_EMAIL" \
  --form file=@"$RESULTS_ARCHIVE" \
  --form version="$COVERITY_SCAN_VERSION" \
  --form description="$COVERITY_SCAN_DESCRIPTION" \
  "$UPLOAD_URL")
status_code=$(echo "$response" | sed -n '$p')
if [ "${status_code:0:1}" == "2" ]; then
  echo -e "\033[33;1mCoverity Scan upload successful.\033[0m"
else
  TEXT=$(echo "$response" | sed '$d')
  echo -e "\033[33;1mCoverity Scan upload failed: $TEXT.\033[0m"
  exit 1
fi

# EOF
