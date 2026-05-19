#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
# SPDX-License-Identifier: GPL-2.0-only
#

import argparse
import collections
import enum
import json
import logging
import os
import pathlib
import sys
import tempfile
import urllib

import git
import otava.analysis
import requests

sys.path.insert(0, str((pathlib.Path(__file__).parents[1] / "common").absolute()))
import benchmark
import lava_submit
import s3conf

s3conf.S3_STORAGE_PATH = "{}/results/benchmarks/lttng-tools".format(s3conf.S3_BASE_DIR)

default_branches = {
    "master": "da70f9608bc127824ecb6f602a14d9321d63c583",
    "stable-2.15": "85229b43860092c0f96529371125f992f2bf8123",
    "stable-2.14": "b4a64907f540ada5e39de62ba9f26a4bbaa48fdb",
    "stable-2.13": "b3c1d080baf1a854af6ef1843b70008f81dbf703",
}


def get_environment_context():
    return {
        "babeltrace_repo": os.getenv(
            "BABELTRACE_REPO", "https://github.com/efficios/babeltrace.git"
        ),
        "ci_repo": os.getenv("LTTNG_CI_REPO", "https://github.com/lttng/lttng-ci.git"),
        "ci_branch": os.getenv("LTTNG_CI_BRANCH", "master"),
        "kernel_url": os.getenv(
            "LAVA_KERNEL_URL",
            "{}/system-tests/kernel/{}.baremetal.bzImage".format(
                s3conf.S3_ANONYMOUS_URL,
                os.getenv(
                    "KERNEL_COMMIT_ID", "f6044d1fd846ed1ae457975738267214b538a222"
                ),
            ),
        ),
        "kernel_headers_url": os.getenv(
            "LAVA_KERNEL_HEADERS_URL",
            "{}/system-tests/kernel/{}.baremetal.headers.tar.xz".format(
                s3conf.S3_ANONYMOUS_URL,
                os.getenv(
                    "KERNEL_COMMIT_ID", "f6044d1fd846ed1ae457975738267214b538a222"
                ),
            ),
        ),
        "nfsrootfs_url": os.getenv(
            "NFS_ROOT_URL",
            "{}/rootfs/rootfs_amd64_trixie_2026-02-06.tar.xz".format(
                s3conf.S3_ANONYMOUS_URL
            ),
        ),
        "lttng_modules_repo": os.getenv(
            "LTTNG_MODULES_REPO", "https://github.com/lttng/lttng-modules.git"
        ),
        "lttng_tools_repo": os.getenv(
            "LTTNG_TOOLS_REPO", "https://github.com/lttng/lttng-tools.git"
        ),
        "lttng_tools_benchmarks_repo": os.getenv(
            "LTTNG_TOOLS_BENCHMARKS_REPO",
            "https://github.com/lttng/lttng-tools-benchmarks.git",
        ),
        "lttng_tools_benchmarks_branch": os.getenv(
            "LTTNG_TOOLS_BENCHMARKS_BRANCH", "main"
        ),
        "lttng_ust_repo": os.getenv(
            "LTTNG_UST_REPO", "https://github.com/lttng/lttng-ust.git"
        ),
        "tailleur_repo": os.getenv(
            "TAILLEUR_REPO", "https://github.com/efficios/tailleur.git"
        ),
        "tailleur_branch": os.getenv("TAILLEUR_BRANCH", "main"),
        "urcu_repo": os.getenv(
            "URCU_REPO", "https://github.com/urcu/userspace-rcu.git"
        ),
    }


def get_benchmark_state(commit):
    path = os.path.join(s3conf.S3_STORAGE_PATH, commit)
    fail_path = os.path.join(path, "failed")
    result_path = os.path.join(path, "benchmarks.json")

    # Check if the benchmark failed
    resp = requests.head("{}/{}".format(s3conf.S3_ANONYMOUS_URL, fail_path))
    if resp.status_code == 200:
        return benchmark.BenchmarkState.BUILD_FAILURE

    # Check if the results are there
    resp = requests.head("{}/{}".format(s3conf.S3_ANONYMOUS_URL, result_path))
    if resp.status_code != 200:
        return benchmark.BenchmarkState.MISSING_BENCHMARK_RESULTS

    return benchmark.BenchmarkState.COMPLETE


def get_benchmark_results(commit):
    path = os.path.join(s3conf.S3_STORAGE_PATH, commit)
    result_path = os.path.join(path, "benchmarks.json")
    response = requests.get("{}/{}".format(s3conf.S3_ANONYMOUS_URL, result_path))
    if response.status_code != 200:
        raise Exception("No data available for '{}'".format(result_path))

    return json.loads(response.content)


def launch_jobs(commits, wait=False, dry_run=False, batch_size=0, max_batches=0):
    chunks = [commits]
    if batch_size > 0:
        chunks = [
            commits[i : i + batch_size] for i in range(0, len(commits), batch_size)
        ]

    logging.debug("{} commits in {} jobs".format(len(commits), len(chunks)))
    submitted = 0
    failed = 0
    passed = 0
    for index, commits in enumerate(chunks):
        if len(commits) == 0:
            logging.debug("No commits to submit for chunk index {}".format(index))
            continue

        logging.info(
            "Job {}/{}{}".format(
                index + 1,
                max(len(chunks), max_batches),
                " (not submitted)" if dry_run else "",
            )
        )

        submitted += 1
        result = lava_submit.submit(
            "lttng-tools_benchmark.yaml.j2",
            extra_context={
                "commits": " ".join(commits),
                # ~ 1hr / commit including machine bootstrap
                "job_timeout_hours": len(commits),
            }
            | get_environment_context(),
            wait_for_completion=wait,
            debug=dry_run,
        )

        if wait and not dry_run:
            state, health, failures = result
            if state != "Finished" or health != "Complete" or failures:
                failed += 1
            else:
                passed += 1

        if max_batches > 0 and index + 1 >= max_batches:
            logging.info("Stopping after {} batches".format(max_batches))
            break

    return (submitted, passed, failed)


def generate_asv_report(repo_path, branches, benchmark_data, output):
    import asv
    import bs4

    results_dir = tempfile.TemporaryDirectory()
    conf = asv.config.Config()
    conf.html_dir = str(output)
    conf.project = str(repo_path)
    conf.project_url = "https://lttng.org/"
    # conf.branches = branches.keys()
    conf.dvcs = "git"
    conf.repo = str(repo_path)
    conf.results_dir = results_dir.name
    conf.branches = ["origin/{}".format(x) for x in branches.keys()]

    # Write machine.json
    machine = asv.machine.Machine()
    machine.machine = "lava"
    machine.hardcoded_machine_name = "lava"
    machine.os = "Linux"
    machine.arch = "x86_64"
    machine.cpu = "Intel(R) Xeon(R) CPU E5-2630 v3 @ 2.40GHz"
    machine.num_cpu = "32"
    machine.ram = "128GiB"
    machine.save(conf.results_dir)

    # Each metric maps to a "benchmark" in ASV
    # Create a dict index by (name, version) of the benchmark metrics
    benchmarks_by_name_and_version = dict()
    for data in benchmark_data:
        for result in data["results"]:
            version = result["version"][0]
            for metric in result["data"]:
                benchmark_name = "{}.{}.{}".format(
                    result["name"], result["parameters"]["_name_"], metric
                )
                if benchmark_name not in benchmarks_by_name_and_version:
                    benchmarks_by_name_and_version[benchmark_name] = dict()

                if version not in benchmarks_by_name_and_version[benchmark_name]:
                    unit = result["metrics"].get("unit", "<unknown>")
                    benchmarks_by_name_and_version[benchmark_name][version] = {
                        "name": benchmark_name,
                        "version": version,
                        "params": list(),
                        "param_names": list(),
                        "type": "time" if "seconds" in unit else "track",
                        "unit": unit,
                    }

    asv_benchmark_list = list()
    for entry in benchmarks_by_name_and_version.values():
        for b in entry.values():
            asv_benchmark_list.append(b)

    benchmark_set = asv.benchmarks.Benchmarks(conf, asv_benchmark_list)
    benchmark_set.save()

    # Fill in the data
    for data in benchmark_data:
        commit = data["metadata"]["lttng-tools_commit"]
        asv_result = asv.results.Results(
            {"machine": "lava"}, list(), commit, 0, "none", "lava", dict()
        )
        for result in data["results"]:
            for metric, value in result["data"].items():
                benchmark_name = "{}.{}.{}".format(
                    result["name"], result["parameters"]["_name_"], metric
                )
                try:
                    v = aggregate_data(value)
                except TypeError as e:
                    logging.warning(
                        "Could not convert to float with {}: {}".format(metric, str(e))
                    )
                    continue

                runner_result = asv.runner.BenchmarkResult([v], [], [1], 0, "", None)
                asv_result.add_result(
                    benchmarks_by_name_and_version[benchmark_name][
                        result["version"][0]
                    ],
                    runner_result,
                    record_samples=False,
                )

        logging.info("Saving result(s) for commit {}".format(commit))
        asv_result.save(conf.results_dir)

    # Update
    conf.project = "LTTng-tools"
    publish = asv.commands.publish.Publish()
    publish.run(conf, pull=False)

    # Load index.html and download scripts and CSS so that only local ones are
    # used. This allows the publish reports in Jenkins to work without adjusting
    # the CSP for the site.
    soup = None
    with open(os.path.join(conf.html_dir, "index.html"), "r") as f:
        soup = bs4.BeautifulSoup(f, "html.parser")

    for script in soup("script"):
        if "src" not in script.attrs.keys():
            continue

        url = urllib.parse.urlparse(script["src"])
        if url.netloc == "":
            continue

        request = requests.get(script["src"])
        with open(os.path.join(conf.html_dir, os.path.basename(url.path)), "wb") as f:
            f.write(request.content)

        # Update src element
        script["src"] = os.path.basename(url.path)

    for link in soup("link"):
        if "href" not in link.attrs.keys():
            continue

        url = urllib.parse.urlparse(link["href"])
        if url.netloc == "":
            continue

        request = requests.get(link["href"])
        with open(os.path.join(conf.html_dir, os.path.basename(url.path)), "wb") as f:
            f.write(request.content)

        link["href"] = os.path.basename(url.path)

    # Write out updated HTML
    with open(os.path.join(conf.html_dir, "index.html"), "w") as f:
        f.write(str(soup))


def mean(data):
    total = 0.0
    for d in data:
        total += float(d)
    return total / len(data)


def aggregate_data(data, fn=mean):
    if type(data) is list:
        d = [aggregate_data(x, fn) for x in data]
        return fn(d)
    else:
        return float(data)


def get_results_by_metric(benchmark_data: list):
    # {key: [(commit, value, benchmark_version), ...], ...}
    metrics = dict()
    for data in benchmark_data:
        commit = data["metadata"]["lttng-tools_commit"]
        for result in data["results"]:
            for m_key in result["metrics"].keys():
                entry_key = "{}.{}.{}.{}".format(
                    result["name"],
                    "v{}".format(result["version"][0]),
                    result["parameters"].get("_name_", "default"),
                    m_key,
                )
                if entry_key not in metrics:
                    metrics[entry_key] = list()

                try:
                    metric_data = aggregate_data(result["data"][m_key])
                except TypeError as e:
                    logging.warning(
                        "Could not convert to float with key {}: {}".format(
                            m_key, str(e)
                        )
                    )
                    continue

                metrics[entry_key].append(
                    (commit, metric_data, result["metrics"][m_key].get("direction", 1))
                )

    return metrics


def render_changepoints_tsv(
    commits, benchmarks, metrics, changepoints, output_fd, include_changepoint_line=True
):
    # Printed table output
    keys = list(metrics.keys())
    metadata_keys = [
        "lttng-tools_commit",
        "lttng-tools_commit_description",
        "lttng-modules_commit",
        "lttng-ust_commit",
        "urcu_commit",
        "babeltrace_commit",
    ]

    print("\t".join(metadata_keys + keys), file=output_fd)
    for commit in commits.keys():
        commit_changepoints = [x for x in changepoints if x.changed_commit == commit]
        if len(commit_changepoints) > 0 and include_changepoint_line:
            line_data = ["" for x in metadata_keys + keys]
            offset = len(metadata_keys)
            for c in commit_changepoints:
                print_index = keys.index(c.metric)
                line_data[print_index + offset] = "{:+n} ({:+.2%})".format(
                    c.stats.mean_2 - c.stats.mean_1,
                    (c.stats.mean_2 - c.stats.mean_1) / c.stats.mean_1,
                )

            print("\t".join(line_data), file=output_fd)

        data_by_commit = list()
        for key in metadata_keys:
            data_by_commit.append(benchmarks[commits[commit]]["metadata"].get(key, ""))

        for key in keys:
            found = False
            for entry in metrics[key]:
                if entry[0] == commit:
                    data_by_commit.append(str(entry[1]))
                    found = True
                    break

            if not found:
                data_by_commit.append("")

        print("\t".join(data_by_commit), file=output_fd)


def changepoint_to_dict(c):
    return {
        "previous_commit": c.previous_commit,
        "changed_commit": c.changed_commit,
        "metric": c.metric,
        "direction": c.direction,
        "index": int(c.index),
        "qhat": float(c.qhat),
        "is_regression": 1 if c.is_regression else 0,
        "stats": {
            "mean_1": c.stats.mean_1,
            "std_1": c.stats.std_1,
            "mean_2": c.stats.mean_2,
            "std_2": c.stats.std_2,
        },
    }


def render_changepoints(
    commits, benchmarks, metrics, changepoints, output_fd, output_format
):
    # @TODO: JSON output
    if output_format.startswith("tsv"):
        render_changepoints_tsv(
            commits,
            benchmarks,
            metrics,
            changepoints,
            output_fd,
            include_changepoint_line=":no_changepoint" not in output_format,
        )
    elif output_format == "json":
        json.dump([changepoint_to_dict(c) for c in changepoints], output_fd)
    else:
        raise RuntimeError("Unknown output format '{}'".format(output_format))


def changepoint_analysis(benchmarks, output_fd=sys.stdout, output_format="tsv"):
    commits = {
        x["metadata"]["lttng-tools_commit"]: index for index, x in enumerate(benchmarks)
    }
    # @TODO: Filtering
    # @TODO Custom aggregation functions?
    # @TODO: since, window, p-value, magnitude cutoff
    metrics = get_results_by_metric(benchmarks)
    changepoints = list()
    for metric, data in metrics.items():
        values = [x[1] for x in data]
        metric_changepoints, weak_changepoints = otava.analysis.compute_change_points(
            values
        )
        logging.debug(
            "Identified {} changepoints and {} weak changepoints for metric {}".format(
                len(metric_changepoints), len(weak_changepoints), metric
            )
        )
        for c in metric_changepoints:
            c.previous_commit = data[c.index - 1][0]
            c.changed_commit = data[c.index][0]
            c.metric = metric
            c.direction = data[c.index][2]
            c.is_regression = (c.direction > 0 and c.stats.mean_2 < c.stats.mean_1) or (
                c.direction < 0 and c.stats.mean_2 > c.stats.mean_1
            )
            logging.info(
                "{} in {} between {} and {}: from {} ({}) to {} ({})".format(
                    "Regression" if c.is_regression else "Change",
                    c.metric,
                    c.previous_commit,
                    c.changed_commit,
                    c.stats.mean_1,
                    c.stats.std_1,
                    c.stats.mean_2,
                    c.stats.std_2,
                )
            )
            changepoints.append(c)

    logging.info("{} changepoints".format(len(changepoints)))
    if output_fd is not None:
        render_changepoints(
            commits, benchmarks, metrics, changepoints, output_fd, output_format
        )

    return changepoints


def _get_parser():
    parser = benchmark.get_parser(
        description="LTTng-tools benchmark launcher", default_branches=default_branches
    )
    subparsers = parser.add_subparsers()
    benchmark.add_changepoint_analysis_parser(
        subparsers,
        func=lambda args: benchmark.cmd_changepoint_analysis(
            args,
            get_benchmark_state,
            get_benchmark_results,
            changepoint_analysis,
        ),
    )
    benchmark.add_get_benchmark_data_parser(
        subparsers,
        func=lambda args: benchmark.cmd_get_benchmark_data(
            args, get_benchmark_state, get_benchmark_results
        ),
    )
    benchmark.add_gen_jobs_parser(
        subparsers,
        func=lambda args: benchmark.cmd_generate_jobs(
            args, get_benchmark_state, launch_jobs
        ),
    )
    benchmark.add_gen_asv_parser(
        subparsers,
        func=lambda args: benchmark.cmd_generate_asv(
            args, get_benchmark_state, get_benchmark_results, generate_asv_report
        ),
    )
    return parser


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = _get_parser()
    args = parser.parse_args()
    if args.log_level:
        logging.getLogger().setLevel(args.log_level)

    if "commits" in args:
        args.commits = [x for x in args.commits.split(",") if x]

    if "branches" in args and type(args.branches) is str:
        _branches = [x for x in args.branches.split(",") if x]
        args.branches = dict()
        for b in _branches:
            split = b.split(":")
            cutoff = None
            if len(split) == 2:
                cutoff = split[1]
            args.branches[split[0]] = cutoff

    if "func" not in args:
        parser.error("No sub-command specified")

    sys.exit(args.func(args))
