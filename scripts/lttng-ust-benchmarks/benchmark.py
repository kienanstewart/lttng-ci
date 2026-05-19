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
import requests

sys.path.insert(0, str((pathlib.Path(__file__).parents[1] / "common").absolute()))
import benchmark
import lava_submit
import s3conf

s3conf.S3_STORAGE_PATH = "/system-tests/results/benchmarks/lttng-ust"


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
        "lttng_ust_benchmarks_repo": os.getenv(
            "LTTNG_UST_BENCHMARKS_REPO",
            "https://github.com/lttng/lttng-ust-benchmarks.git",
        ),
        "lttng_ust_benchmarks_branch": os.getenv(
            "LTTNG_UST_BENCHMARKS_BRANCH", "master"
        ),
        "lttng_ust_repo": os.getenv(
            "LTTNG_UST_REPO", "https://github.com/lttng/lttng-ust.git"
        ),
        "urcu_repo": os.getenv(
            "URCU_REPO", "https://github.com/urcu/userspace-rcu.git"
        ),
    }


def get_commit_list(
    repo,
    branches=dict(),
    current_commit=None,
    other_commits=list(),
    regression=False,
    tags_only=False,
):
    repo.git.fetch()

    commits = set()
    if regression and len(other_commits) == 0:
        if current_commit is None:
            current_commit = repo.head.commit
        else:
            current_commit = repo.commit(current_commit)

        commits.add(str(current_commit))
        logging.debug("Adding current commit '{}'".format(str(current_commit)))
        for parent in current_commit.parents:
            logging.debug(
                "Adding commit '{}' as parent of commit '{}'".format(
                    str(parent), str(current_commit)
                )
            )
            commits.add(str(parent))

        # This is relative to the current state, not the current_commit
        tag = repo.git().describe(str(current_commit), abbrev=0)
        if tag:
            logging.debug(
                "Tag relative to commit '{}' is '{}' (id:{})".format(
                    str(current_commit), tag, str(repo.tag(tag).commit)
                )
            )
            commits.add(str(repo.tag(tag).commit))

    if current_commit is None and len(other_commits) == 0:
        if len(branches) == 0:
            branches = {"master": None}

        for branch, cutoff in branches.items():
            target = "origin/{}".format(branch)
            if cutoff:
                target = "{}..{}".format(cutoff, target)

            for commit in repo.git.log(target, pretty="format:%H", reverse=True).split(
                "\n"
            ):
                commits.add(commit)

    if current_commit is not None:
        commits.add(str(current_commit))

    if len(other_commits) > 0:
        commits = commits.union(other_commits)
        commits.add(current_commit)

    if tags_only:
        tagged_commits = {str(x.commit) for x in repo.tags}
        commits = commits.intersection(tagged_commits)

    return list(commits)


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

    # @TODO: Should the result file be validated?
    return benchmark.BenchmarkState.COMPLETE


def get_benchmark_results(commit):
    path = os.path.join(s3conf.S3_STORAGE_PATH, commit)
    result_path = os.path.join(path, "benchmarks.json")
    response = requests.get("{}/{}".format(s3conf.S3_ANONYMOUS_URL, result_path))
    if response.status_code != 200:
        raise Exception("No data available for '{}'".format(result_path))

    return json.loads(response.content)


def launch_jobs(commits, batch_size=0, max_batches=0, wait=True, dry_run=False):
    """
    Return a tuple (nJobs, nPassed, nFailed)
    """
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
        logging.info(
            "Job {}/{}{}".format(
                index + 1,
                max(len(chunks), max_batches),
                " (not submitted)" if dry_run else "",
            )
        )

        submitted += 1
        result = lava_submit.submit(
            "lttng-ust_benchmark.yaml.j2",
            extra_context={
                "commits": " ".join(commits),
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


def cmd_generate_asv(args):
    if not args.repo_path.is_dir():
        raise Exception(
            "repo-path `{}` is not a directory".format(args.repo_path),
        )

    if args.output.exists():
        raise Exception("Output directory `{}` already exists".format(args.output))

    benchmark_data = list()
    if len(args.input_files) == 0:
        repo = git.Repo(args.repo_path)
        commits = get_commit_list(
            repo,
            args.branches,
            current_commit=args.commits[0] if len(args.commits) > 0 else None,
            other_commits=args.commits[1:],
            regression=args.regression,
            tags_only=args.tags_only,
        )
        for commit in commits:
            if get_benchmark_state(commit) == benchmark.BenchmarkState.COMPLETE:
                benchmark_data.append(get_benchmark_results(commit))
            else:
                logging.warning("Results for commit '{}' not available".format(commit))

    else:
        for f in args.input_files:
            if not f.exists():
                raise Exception("Input file '{}' does not exist".format(f))

            with open(f, "r") as fp:
                benchmark_data.append(json.load(fp))

    generate_asv_report(args.repo_path, args.branches, benchmark_data, args.output)


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

    # Benchmarks
    benchmark_names = set()
    benchmark_params = set()
    for datum in benchmark_data:
        benchmark_params.update(datum["average"].keys())
        for key in datum["average"].keys():
            benchmark_names.update(datum["average"][key].keys())

    benchmarks = {
        x: {
            "name": x,
            "params": list(),
            "param_names": list(),
            "type": "track" if "_pct" in x else "time",
            "unit": (
                "percent"
                if "_pct" in x
                else ("nanoseconds" if "ns_" in x else "seconds")
            ),
            "version": 1,
        }
        for x in benchmark_names
    }
    benchmark_set = asv.benchmarks.Benchmarks(conf, benchmarks.values())
    benchmark_set.save()

    # Fill in the data
    for benchmark_datum in benchmark_data:
        commit = benchmark_datum["metadata"]["lttng-ust_commit"]
        asv_result = asv.results.Results(
            {"machine": "lava"}, list(), commit, 0, "none", "lava", dict()
        )
        # Use the average stored average for the moment
        for param in benchmark_datum["average"].keys():
            for key, value in benchmark_datum["average"][param].items():
                benchmark = benchmarks[key]
                runner_result = asv.runner.BenchmarkResult(
                    [value], [], [1], 0, "", None
                )
                asv_result.add_result(benchmark, runner_result, record_samples=False)

        logging.info("Saving result(s) for commit {}".format(commit))
        asv_result.save(conf.results_dir)

    # Update
    conf.project = "LTTng-UST"
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


def cmd_generate_jobs(args):
    """
    Runs the command and returns the exit code
    """
    if not args.repo_path.is_dir():
        raise Exception(
            "repo-path `{}` is not a directory".format(args.repo_path),
        )

    repo = git.Repo(args.repo_path)
    commits = get_commit_list(
        repo,
        args.branches,
        current_commit=args.commits[0] if len(args.commits) > 0 else None,
        other_commits=args.commits[1:],
        regression=args.regression,
        tags_only=args.tags_only,
    )

    logging.debug("{} commits to potentially run benchmarks for".format(len(commits)))
    if not args.force_jobs:
        # Filter out commits whose benchmarks are complete or failed
        commits = [
            commit
            for commit in commits
            if get_benchmark_state(commit)
            == benchmark.BenchmarkState.MISSING_BENCHMARK_RESULTS
        ]

    logging.info("{} commits to run benchmarks for".format(len(commits)))
    submitted, passed, failed = launch_jobs(
        commits,
        wait=not args.no_wait,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        max_batches=args.max_batches,
    )
    logging.info(
        "{} submitted jobs: {} passed, {} failed".format(submitted, passed, failed)
    )
    if failed != 0:
        return 1

    return 0


def cmd_regression_check(args):
    benchmark_data = list()
    if len(args.input_files) == 0:
        # Fetch from storage
        repo = git.Repo(args.repo_path)
        commits = get_commit_list(
            repo,
            args.branches,
            current_commit=args.commits[0] if len(args.commits) > 0 else None,
            other_commits=args.commits[1:],
            regression=True,
            tags_only=False,
        )
        for commit in commits:
            if get_benchmark_state(commit) == benchmark.BenchmarkState.COMPLETE:
                benchmark_data.append(get_benchmark_results(commit))
            else:
                logging.warning("Results for commit '{}' not available".format(commit))
    else:
        for f in args.input_files:
            if not f.exists():
                raise Exception("Input file '{}' does not exist".format(f))

            with open(f, "r") as fp:
                benchmark_data.append(json.load(fp))

    if len(benchmark_data) < 2:
        raise Exception(
            "Not enough data to compare, only {} results available".format(
                len(benchmark_data)
            )
        )

    benchmark_filter = args.benchmarks.split(",")
    regressions = regression_check(
        benchmark_data[0],
        benchmark_data[1:],
        args.significance_level,
        args.failure_threshold,
        (
            None
            if len(benchmark_filter) == 0 or "all" in benchmark_filter
            else benchmark_filter
        ),
    )
    return 1 if len(regressions) > 0 else 0


def regression_check(
    current_commit_data,
    other_commit_data,
    significance_level=0.05,
    failure_threshold=0.01,
    benchmark_filter=None,
    print_results=True,
):
    import numpy
    import scipy

    if len(other_commit_data) < 1:
        raise Exception("No other data to check current commit data against")

    # A lot of massaging of the benchmark data is done here
    regressions = list()
    evaluation_data = {
        "metadata": {
            "current_commit": current_commit_data["metadata"]["lttng-ust_commit"],
            "significance_level": significance_level,
            "failure_threshold": failure_threshold,
        },
        "data": {
            x: {"samples": y}
            for x, y in get_benchmark_data_samples(
                current_commit_data, benchmark_filter
            ).items()
        },
        "comparison_to": dict(),
    }
    for benchmark in evaluation_data["data"].keys():
        values = evaluation_data["data"][benchmark]["samples"]
        evaluation_data["data"][benchmark] |= {
            "cv": scipy.stats.variation(values),
            "mean": numpy.mean(values),
            "median": numpy.median(values),
            "stddev": numpy.std(values),
        }

    for b in other_commit_data:
        # commit_hash: { 'benchmarkX': { 'samples': [N0, N1, ...], 'U': U1, 'p-value': P, 'reject_null_hypothesis': False}
        commit = b["metadata"]["lttng-ust_commit"]
        evaluation_data["comparison_to"][commit] = dict()
        for key, values in get_benchmark_data_samples(b, benchmark_filter).items():
            U1 = None
            p = None
            reject_null = False
            if key not in evaluation_data["data"]:
                logger.warning(
                    "Cannot compare '{}' from commit {} to current commit {}: no such data in current commit".format(
                        key, commit, evaluation_data["current_commit"]
                    )
                )
            else:
                U1, p = scipy.stats.mannwhitneyu(
                    evaluation_data["data"][key]["samples"], values
                )
                if p < significance_level:
                    reject_null = True

            comparison_result = {
                "samples": values,
                "U": U1,
                "p-value": p,
                "reject_null_hypothesis": reject_null,
                "cv": scipy.stats.variation(values),
                "mean": numpy.mean(values),
                "median": numpy.median(values),
                "stddev": numpy.std(values),
                "has_regression": True,
            }
            delta_mean = (
                evaluation_data["data"][key]["mean"] - comparison_result["mean"]
            )
            delta_mean_pct = delta_mean / comparison_result["mean"]

            delta_median = (
                evaluation_data["data"][key]["median"] - comparison_result["median"]
            )
            delta_median_pct = delta_median / comparison_result["median"]
            comparison_result |= {
                "delta_mean": delta_mean,
                "delta_mean_pct": delta_mean_pct,
                "delta_median": delta_median,
                "delta_median_pct": delta_median_pct,
            }

            if reject_null and (
                (delta_mean > 0.0 and delta_mean_pct > failure_threshold)
                or (delta_median > 0.0 and delta_median_pct > failure_threshold)
            ):
                logging.debug(
                    "delta_mean: {} ({}%), delta_median: {} ({}%)".format(
                        delta_mean,
                        delta_mean_pct * 100.0,
                        delta_median,
                        delta_median_pct * 100.0,
                    )
                )
                logging.info(
                    "Regression detect in commit {} relative to commit {} in benchmark {}".format(
                        evaluation_data["metadata"]["current_commit"], commit, key
                    )
                )
                comparison_result["has_regression"] = True
                regressions.append("{}:{}".format(commit, key))

            evaluation_data["comparison_to"][commit][key] = comparison_result

    if print_results:
        current_commit = evaluation_data["metadata"]["current_commit"]
        other_commits = list(evaluation_data["comparison_to"].keys())
        benchmarks = list(evaluation_data["data"].keys())
        for benchmark in benchmarks:
            print("Benchmark: {}".format(benchmark))
            for commit in other_commits:
                if benchmark not in evaluation_data["comparison_to"][commit]:
                    logging.warning(
                        "No comparison from current commit {} to commit {} with benchmark {}".format(
                            current_commit, commit, benchmark
                        )
                    )
                    continue

                print(
                    "[{} vs {}] U={}, p={}, reject_null_hypothesis={}".format(
                        current_commit,
                        commit,
                        evaluation_data["comparison_to"][commit][benchmark]["U"],
                        evaluation_data["comparison_to"][commit][benchmark]["p-value"],
                        evaluation_data["comparison_to"][commit][benchmark][
                            "reject_null_hypothesis"
                        ],
                    )
                )
                print(
                    "Mean: {} vs {}, Δ={}, Δ%={}%".format(
                        evaluation_data["data"][benchmark]["mean"],
                        evaluation_data["comparison_to"][commit][benchmark]["mean"],
                        evaluation_data["comparison_to"][commit][benchmark][
                            "delta_mean"
                        ],
                        evaluation_data["comparison_to"][commit][benchmark][
                            "delta_mean_pct"
                        ]
                        * 100.0,
                    )
                )
                print(
                    "Median: {} vs {}, Δ={}, Δ%={}%".format(
                        evaluation_data["data"][benchmark]["median"],
                        evaluation_data["comparison_to"][commit][benchmark]["median"],
                        evaluation_data["comparison_to"][commit][benchmark][
                            "delta_median"
                        ],
                        evaluation_data["comparison_to"][commit][benchmark][
                            "delta_median_pct"
                        ]
                        * 100.0,
                    )
                )
                print()
            print()
    return regressions


def get_benchmark_data_samples(benchmark_data, benchmark_filter=None):
    if len(benchmark_data["data"].keys()) != 1:
        raise Exception(
            "Cannot handle benchmark data with multiple parameters, commit={}".format(
                benchmark_data["metadata"]["lttng-ust_commit"]
            )
        )

    key = list(benchmark_data["data"].keys())[0]
    samples = dict()
    for entry in benchmark_data["data"][key]:
        # '{'basic': {'baseline': {'run_time': N, ...}, ...}, }'
        for benchmark_name, value in flatten_dict(entry).items():
            if benchmark_filter and benchmark_name not in benchmark_filter:
                continue

            if ".args." in benchmark_name:
                continue

            if benchmark_name not in samples:
                samples[benchmark_name] = list()

            samples[benchmark_name].append(value)

    return samples


def flatten_dict_internal(prefix, data, dst):
    if issubclass(data.__class__, str):
        dst[prefix] = data
    elif issubclass(data.__class__, collections.abc.Mapping):
        for key in data.keys():
            fullprefix = prefix + "." + key if len(prefix) > 0 else key
            flatten_dict_internal(fullprefix, data[key], dst)
    elif issubclass(data.__class__, collections.abc.Iterable):
        i = 0
        for value in data:
            fullprefix = prefix + "." + str(i)
            flatten_dict_internal(fullprefix, value, dst)
            i += 1
    elif data is not None:
        dst[prefix] = data


def flatten_dict(data):
    dst = dict()
    flatten_dict_internal("", data, dst)
    return dst


def _get_parser():
    parser = argparse.ArgumentParser(description="LTTng-UST benchmark launcher")
    parser.add_argument(
        "-s",
        "--silent",
        help="Only output errors",
        dest="log_level",
        action="store_const",
        const=logging.WARNING,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        help="Increase verbosity",
        dest="log_level",
        action="store_const",
        const=logging.DEBUG,
    )
    parser.add_argument(
        "--repo-path",
        type=pathlib.Path,
        required=True,
        help="The path a local copy of the lttng-ust repo",
    )
    parser.add_argument(
        "--branches",
        # Cutoff from git merge-base origin/BRANCH origin/master,
        # for the master branch cutoff at the last time the branch
        # was forked
        default={
            "master": "871e256dcc4c2799a5386f7d9f6e9e78307ee688",
            "stable-2.15": "871e256dcc4c2799a5386f7d9f6e9e78307ee688",
            "stable-2.14": "d40d5e5e6af9fce8608ef3ba85a92f601a26b867",
            "stable-2.13": "06f280fd4452f88ce67e622c4961e11ad376f469",
        },
        help="A comma-separated list of branches in the format NAME[:CUTOFF] to check",
    )

    commits_args = (
        ["--commits"],
        {
            "default": "",
            "help": "A comma-separated list of commits to generate jobs before. If `--regression` is picked, the first of the list is considered the 'current' commit for determining any other commits to be also be submitted",
        },
    )
    regression_args = (
        ["--regression"],
        {
            "action": "store_true",
            "default": False,
            "help": "Choose commits to test based on the current commit, previous, and last tag relative to the commit",
        },
    )
    tags_only_args = (
        ["--tags-only"],
        {
            "action": "store_true",
            "default": False,
            "help": "Limit generated jobs to tagged commits",
        },
    )

    subparsers = parser.add_subparsers()
    gen_asv_parser = subparsers.add_parser(
        "generate-asv", help="Generate output as an ASV static HTML folder"
    )
    gen_asv_parser.add_argument(
        "-o",
        "--output",
        type=pathlib.Path,
        default=pathlib.Path(os.getcwd()) / "output",
        help="The output folder",
    )
    gen_asv_parser.add_argument(
        "-i",
        "--input-files",
        type=pathlib.Path,
        default=list(),
        action="append",
        help="Input benchmark JSON results files to use, instead of downloading from object storage",
    )
    gen_asv_parser.add_argument(*commits_args[0], **commits_args[1])
    gen_asv_parser.add_argument(*regression_args[0], **regression_args[1])
    gen_asv_parser.add_argument(*tags_only_args[0], **tags_only_args[1])
    gen_asv_parser.set_defaults(func=cmd_generate_asv)

    gen_jobs_parser = subparsers.add_parser("generate-jobs", help="Generate jobs")
    gen_jobs_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Do all work except submitting the jobs to LAVA",
    )
    gen_jobs_parser.add_argument(*commits_args[0], **commits_args[1])
    gen_jobs_parser.add_argument(*regression_args[0], **regression_args[1])
    gen_jobs_parser.add_argument(*tags_only_args[0], **tags_only_args[1])
    gen_jobs_parser.add_argument(
        "--batch-size",
        default=10,
        type=int,
        help="The number of commits to include in each LAVA job",
    )
    gen_jobs_parser.add_argument(
        "--max-batches", default=0, type=int, help="Only run up to N LAVA jobs"
    )
    gen_jobs_parser.add_argument(
        "--force-jobs",
        action="store_true",
        default=False,
        help="Queue jobs for commits that have been marked as failed or complete",
    )
    gen_jobs_parser.add_argument(
        "--no-wait",
        action="store_true",
        default=False,
        help="Do not wait for LAVA jobs to complete before returning",
    )
    gen_jobs_parser.set_defaults(func=cmd_generate_jobs)

    regression_parser = subparsers.add_parser(
        "regression",
        help="Check current commit for regressions against previous commits",
    )
    regression_parser.add_argument(*commits_args[0], **commits_args[1])
    regression_parser.set_defaults(func=cmd_regression_check)
    regression_parser.add_argument(
        "-i",
        "--input-files",
        type=pathlib.Path,
        default=list(),
        action="append",
        help="Input benchmark JSON results files to use, instead of downloading from object storage. The first file is considered the 'current commit' when checking for regressions. This argument may be specified multiple times.",
    )
    regression_parser.add_argument(
        "--significance-level",
        default=0.05,
        type=float,
        help="The significance level for rejecting the null hypothesis of the Mann-Whitney U test",
    )
    regression_parser.add_argument(
        "--failure-threshold",
        default=0.01,
        type=float,
        help="The minimum percent difference in benchmarks to signal when the null hypothesis is rejected",
    )
    regression_parser.add_argument(
        "-b",
        "--benchmarks",
        default="all",
        help="A comma-separated list of benchmarks to check. Use `all` to check each available benchmark. Example: `gen-tp.tracing_enabled.ns_per_event`",
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
