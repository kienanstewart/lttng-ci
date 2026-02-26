#!/usr/bin/bash

function enable_coredumps()
{
    DIR="${1:-${SCRATCH_DIR}/coredump}"
    mkdir -p "$DIR"
    echo "$DIR/core.%e.%p.%h.%t" > /proc/sys/kernel/core_pattern
    ulimit -c unlimited
}

function enable_performance_cpu_governor()
{
    # Set the cpu governor to performance
    if [ -d /sys/devices/system/cpu/cpu0/cpufreq ]; then
        cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors || find /sys/devices/system/cpu/cpu0/cpufreq/
        echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
        return 0
    else
        echo "Warning: /sys/devices/system/cpu/cpu0/cpufreq doesn't exist, can't set scaling_governor" >&2
        return 1
    fi
}

function upload_artifact()
{
    set +x
    local local_file=$1
    local s3_key=$2
    local md5 CURL_RC ERR_LOG
    CURL_RC="$(mktemp)"
    ERR_LOG="$(mktemp)"

    md5="$(openssl md5 -binary "$local_file" | openssl base64)"

    # Fetch the S3 keys stored in secrets. Usea a subshell to avoid source into
    # the current context.
    (
        # shellcheck disable=SC1090,SC1091
        source "/lava-${LAVA_JOB_ID}/secrets"
        echo "user = \"$S3_ACCESS_KEY:$S3_SECRET_KEY\""
    ) > "${CURL_RC}"
    if ! curl -v -s -f -T "$local_file" \
        --config "${CURL_RC}" \
        --aws-sigv4 "aws:amz:us-east-1:s3" \
        -H "Content-MD5: $md5" \
        "https://${S3_HOST}/${S3_BUCKET}/${S3_BASE_DIR}/$s3_key" 2> "${ERR_LOG}" ; then
        echo "Upload of '${local_file}' failed" >&2
        cat "${ERR_LOG}"
    fi

    rm -f "${CURL_RC}" "${ERR_LOG}"
    set -x
}

function delete_artifact()
{
    set +x
    local s3_key=$1
    local CURL_RC ERR_LOG
    CURL_RC="$(mktemp)"
    ERR_LOG="$(mktemp)"

    # Fetch the S3 keys stored in secrets. Usea a subshell to avoid source into
    # the current context.
    (
        # shellcheck disable=SC1090,SC1091
        source "/lava-${LAVA_JOB_ID}/secrets"
        echo "user = \"$S3_ACCESS_KEY:$S3_SECRET_KEY\""
    ) > "${CURL_RC}"
    if ! curl -v -s -f \
        -X DELETE \
        --config "${CURL_RC}" \
        --aws-sigv4 "aws:amz:us-east-1:s3" \
        "https://${S3_HOST}/${S3_BUCKET}/${S3_BASE_DIR}/$s3_key" 2> "${ERR_LOG}" ; then
        echo "Deletion of of '${S3_BUCKET}/${S3_BASE_DIR}/${s3_key}' failed" >&2
        cat "${ERR_LOG}"
    fi

    rm -f "${CURL_RC}" "${ERR_LOG}"
    set -x
}

function verlte()
{
    [  "$1" = "$(printf '%s\n%s' "$1" "$2" | sort -V | head -n1)" ]
}

function verlt()
{
    # shellcheck disable=SC2015
    [ "$1" = "$2" ] && return 1 || verlte "$1" "$2"
}

function vergte()
{
    [  "$1" = "$(printf '%s\n%s' "$1" "$2" | sort -V | tail -n1)" ]
}

function vergt()
{
    # shellcheck disable=SC2015
    [ "$1" = "$2" ] && return 1 || vergte "$1" "$2"
}

