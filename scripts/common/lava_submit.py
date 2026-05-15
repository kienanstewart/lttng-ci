#!/usr/bin/python3
# SPDX-FileCopyrightText: 2019 Jonathan Rajotte <jonathan.rajotte-julien@efficios.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import os
import pathlib
import sys
import time
import xmlrpc.client

import jinja2
import s3conf
import yaml

# 4.4.194
DEFAULT_KERNEL_COMMIT = "a227f8436f2b21146fc024d84e6875907475ace2"
LAVA_USERNAME = os.environ.get("LAVA_USERNAME")
LAVA_HOST = os.environ.get("LAVA_HOST", "lava-master-03.internal.efficios.com")
LAVA_PROTO = os.environ.get("LAVA_PROTO", "https")


def wait_on(server, jobid):
    """
    Wait for the completion of the job.
    Do not care for result. This is mostly to prevent flooding of lava with
    multiple jobs for the same commit hash. Jenkins is responsible for
    running only one job for job submissions.
    """
    # Check the status of the job every 30 seconds
    jobstatus = server.scheduler.job_state(jobid)["job_state"]
    running = False
    while jobstatus in ["Submitted", "Scheduling", "Scheduled", "Running"]:
        if not running and jobstatus == "Running":
            print("Job started running", flush=True)
            running = True
        time.sleep(30)
        try:
            jobstatus = server.scheduler.job_state(jobid)["job_state"]
        except xmlrpc.client.ProtocolError:
            print("Protocol error, retrying", flush=True)
            continue

    jobhealth = server.scheduler.job_health(jobid)["job_health"]
    has_failing_test_cases = False
    for result in yaml.safe_load(server.results.get_testjob_results_yaml(jobid)):
        if result["metadata"]["result"] != "pass":
            has_failing_test_cases = True
            break

    print(
        "Job ended with {} status (health: {}, has failed test cases: {}).".format(
            jobstatus, jobhealth, has_failing_test_cases
        ),
        flush=True,
    )
    return (jobstatus, jobhealth, has_failing_test_cases)


def get_default_context():
    context = dict()

    context["s3_access_key"] = s3conf.S3_ACCESS_KEY
    context["s3_secret_key"] = s3conf.S3_SECRET_KEY
    context["s3_host"] = s3conf.S3_HOST
    context["s3_bucket"] = s3conf.S3_BUCKET
    context["s3_base_dir"] = s3conf.S3_BASE_DIR
    context["job_timeout_hours"] = 2

    return context


def submit(
    template_file,
    extra_context=dict(),
    debug=False,
    wait_for_completion=True,
    attempts=10,
):
    # Get the S3 secret from the environment
    lava_api_key = None
    if not debug:
        try:
            lava_api_key = os.environ["LAVA2_JENKINS_TOKEN"]
        except Exception as error:
            print(
                "LAVA2_JENKINS_TOKEN not found in the environment variable. Exiting...",
                error,
            )
            return -1

    # Context for the lava job template
    context = get_default_context()
    # Merge, prioritising user-supplied context fields.
    context = context | extra_context

    # Render the lava job template
    jinja_loader = jinja2.FileSystemLoader(
        str((pathlib.Path(__file__).parents[1] / "templates").absolute())
    )
    jinja_env = jinja2.Environment(
        loader=jinja_loader, trim_blocks=True, lstrip_blocks=True
    )
    jinja_template = jinja_env.get_template(template_file)
    render = jinja_template.render(context)

    print("Job to be submitted:", flush=True)
    print(render, flush=True)
    if debug:
        return 0

    server = xmlrpc.client.ServerProxy(
        "%s://%s:%s@%s/RPC2" % (LAVA_PROTO, LAVA_USERNAME, lava_api_key, LAVA_HOST)
    )

    for attempt in range(attempts):
        try:
            jobid = server.scheduler.submit_job(render)
        except xmlrpc.client.ProtocolError as error:
            print(
                "Protocol error on submit, sleeping and retrying. Attempt #{}".format(
                    attempt
                ),
                flush=True,
            )
            time.sleep(5)
            continue
        else:
            break

    print("Lava job id:{}".format(jobid), flush=True)
    print(
        "Lava job URL: https://{}/scheduler/job/{}".format(LAVA_HOST, jobid),
        flush=True,
    )

    if not wait_for_completion:
        return 0

    return wait_on(server, jobid)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Launch baremetal babeltrace test using Lava"
    )
    parser.add_argument("-c", "--commit", required=True, action="append")
    parser.add_argument(
        "-k",
        "--kernel-url",
        required=False,
        default="{}/system-tests/kernel/{}.baremetal.bzImage".format(
            s3conf.S3_HTTP_BUCKET_URL, DEFAULT_KERNEL_COMMIT
        ),
    )
    parser.add_argument("-d", "--debug", required=False, action="store_true")
    args = parser.parse_args()

    context = {
        "commit_hashes": " ".join(args.commit),
        "kernel_url": args.kernel_url,
        "nfsrootfs_url": "https://obj-lava.internal.efficios.com/rootfs/rootfs_amd64_trixie_2026-02-06.tar.xz",
        "ci_repo": "https://github.com/lttng/lttng-ci.git",
        "ci_branch": "master",
        "bt_repo": "https://github.com/efficios/babeltrace.git",
        "trace_default_location": "{}/traces/benchmark/babeltrace/babeltrace_benchmark_trace.tar.gz".format(
            s3conf.S3_HTTP_BUCKET_URL
        ),
        "trace_tools_2_10_location": "{}/traces/benchmark/babeltrace/babeltrace_benchmark_trace-tools-2.10.tar.gz".format(
            s3conf.S3_HTTP_BUCKET_URL
        ),
        "trace_tools_2_14_location": "{}/traces/benchmark/babeltrace/babeltrace_benchmark_trace-tools-2.14.tar.gz".format(
            s3conf.S3_HTTP_BUCKET_URL
        ),
    }
    sys.exit(submit("bt_benchmark.yaml.j2", extra_context=context, debug=args.debug))
