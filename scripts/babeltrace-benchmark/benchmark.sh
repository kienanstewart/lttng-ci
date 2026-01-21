#!/bin/bash
# SPDX-FileCopyrightText: 2019 Jonathan Rajotte-Julien <jonathan.rajotte-julien@efficios.com>
# SPDX-License-Identifier: GPL-3.0-or-later

set -exu

SRC_DIR="$WORKSPACE/src/babeltrace"
SCRIPT_DIR="$WORKSPACE/src/lttng-ci"
RESULTS_DIR="$WORKSPACE/results"

REQUIREMENT_PATH="${SCRIPT_DIR}/scripts/babeltrace-benchmark/requirement.txt"
SCRIPT_PATH="${SCRIPT_DIR}/scripts/babeltrace-benchmark/benchmark.py"

VENV="$WORKSPACE/venv"
export TMPDIR="$WORKSPACE/tmp"

mkdir -p "$TMPDIR"
mkdir -p "$RESULTS_DIR"

git clone -q -b "${LTTNG_CI_BRANCH}" "${LTTNG_CI_REPO}" "$SCRIPT_DIR"

virtualenv --python python3 "$VENV"
set +u
# shellcheck disable=SC1091
. "${VENV}/bin/activate"
set -u

pip install -r "$REQUIREMENT_PATH"


FORCE_ARG=''
if [[ "${BENCHMARK_FORCE}" == "true" ]]; then
    FORCE_ARG="--force-jobs"
fi

TAGS_ARG=''
if [[ "${BENCHMARK_TAGS_ONLY}" == "true" ]]; then
    TAGS_ARG="--tags-only"
fi

# Run the lava jobs
exit_code=0
if [[ "${BENCHMARK_SKIP_SUBMISSION:-}" != "true" ]]; then
    python "$SCRIPT_PATH" \
           --generate-jobs \
           --bt-repo-path "$SRC_DIR" \
           --batch-size "${BENCHMARK_BATCH_SIZE}" \
           $FORCE_ARG $TAGS_ARG \
           --max-batches "${BENCHMARK_MAX_BATCHES}" \
           --ci-repo "${LTTNG_CI_REPO}" \
           --ci-branch "${LTTNG_CI_BRANCH}" \
           --nfs-root-url "${NFS_ROOT_URL}" \
           --kernel-url "${S3_HTTP_BUCKET_URL}/system-tests/kernel/${KERNEL_COMMIT_ID}.baremetal.bzImage" || exit_code=1
fi

if [[ "${BENCHMARK_SKIP_PDF_GENERATION:-}" != "true" ]]; then
    # Generate the report pdf
    python "$SCRIPT_PATH" \
           --generate-report \
           --bt-repo-path "$SRC_DIR" \
           --report-name "${RESULTS_DIR}/babeltrace-benchmark.pdf"
fi

if [[ "${BENCHMARK_SKIP_ASV_GENERATION:-}" != "true" ]]; then
    # If this isn't done, the repo is in a detached head state that
    # asv doesn't like (e.g. `git rev-list master --first-parent master --` fails).
    pushd "${SRC_DIR}"
    git checkout master
    # Need the other branches too
    git branch stable-2.1 origin/stable-2.1
    git branch stable-2.0 origin/stable-2.0
    git branch stable-1.5 origin/stable-1.5
    popd

    python "${SCRIPT_PATH}" \
           --generate-asv-report \
           --bt-repo-path "${SRC_DIR}" \
           ${TAGS_ARG}
    cp -r asv "${RESULTS_DIR}/"
fi

rm -rf "$VENV"
exit $exit_code
