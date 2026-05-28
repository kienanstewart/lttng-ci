#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
# SPDX-License-Identifier: GPL-2.0-only
#

import argparse
import enum
import json
import logging
import os
import pathlib

import git


class BenchmarkState(enum.Enum):
    BUILD_FAILURE = -1
    COMPLETE = 0
    CONTAINS_RUN_FAILURES = 1
    MISSING_BENCHMARK_RESULTS = 2


def cmd_generate_asv(
    args, get_commit_state_func, get_commit_result_func, generate_report_func
):
    if not args.repo_path.is_dir():
        raise Exception(
            "repo-path `{}` is not a directory".format(args.repo_path),
        )

    if not callable(get_commit_state_func):
        raise RuntimeError("get_commit_state_func must be callable")

    if not callable(get_commit_result_func):
        raise RuntimeError("get_commit_result_func must be callable")

    if not callable(generate_report_func):
        raise RuntimeError("generate_report_func must be callable")

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
            if get_commit_state_func(commit) == BenchmarkState.COMPLETE:
                benchmark_data.append(get_commit_result_func(commit))
            else:
                logging.warning("Results for commit '{}' not available".format(commit))

    else:
        for f in args.input_files:
            if not f.exists():
                raise Exception("Input file '{}' does not exist".format(f))

            with open(f, "r") as fp:
                benchmark_data.append(json.load(fp))

    generate_report_func(args.repo_path, args.branches, benchmark_data, args.output)


def cmd_generate_jobs(args, get_commit_state_func, launch_func):
    """
    Runs the command and returns the exit code
    """
    if not args.repo_path.is_dir():
        raise Exception(
            "repo-path `{}` is not a directory".format(args.repo_path),
        )

    if not callable(get_commit_state_func):
        raise RuntimeError("get_commit_state_func must be callable")

    if not callable(launch_func):
        raise RuntimeError("launch_func must be callable")

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
            if get_commit_state_func(commit) == BenchmarkState.MISSING_BENCHMARK_RESULTS
        ]

    logging.info("{} commits to run benchmarks for".format(len(commits)))
    submitted, passed, failed = launch_func(
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


def cmd_regression_check(
    args, get_commit_state_func, get_commit_result_func, regression_check_func
):
    if not callable(get_commit_state_func):
        raise RuntimeError("get_commit_state_func must be callable")

    if not callable(get_commit_result_func):
        raise RuntimeError("get_commit_result_func must be callable")

    if not callable(regression_check_func):
        raise RuntimeError("regression_check_func must be callable")

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
            if get_commit_state_func(commit) == BenchmarkState.COMPLETE:
                benchmark_data.append(get_commit_result_func(commit))
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
    regressions = regression_check_func(
        benchmark_data[-1],
        benchmark_data[0:-1],
        args.significance_level,
        args.failure_threshold,
        (
            None
            if len(benchmark_filter) == 0 or "all" in benchmark_filter
            else benchmark_filter
        ),
    )
    return 1 if len(regressions) > 0 else 0


def get_commit_list(
    repo,
    branches=dict(),
    current_commit=None,
    other_commits=list(),
    regression=False,
    tags_only=False,
):
    repo.git.fetch()

    commits = list()
    if regression and len(other_commits) == 0:
        if current_commit is None:
            current_commit = repo.head.commit
        else:
            current_commit = repo.commit(current_commit)

        # Commits from old -> new
        # This is relative to the current state, not the current_commit
        tag = repo.git().describe(str(current_commit), abbrev=0)
        if tag:
            logging.debug(
                "Tag relative to commit '{}' is '{}' (id:{})".format(
                    str(current_commit), tag, str(repo.tag(tag).commit)
                )
            )
            commits.append(str(repo.tag(tag).commit))

        for parent in current_commit.parents:
            logging.debug(
                "Adding commit '{}' as parent of commit '{}'".format(
                    str(parent), str(current_commit)
                )
            )
            commits.append(str(parent))

    if current_commit is None and len(other_commits) == 0:
        if len(branches) == 0:
            branches = {"master": None}

        if len(branches) > 1:
            logging.warning("Commit ordering with multiple branches is not meaningful")

        for branch, cutoff in branches.items():
            target = "origin/{}".format(branch)
            if cutoff:
                target = "{}..{}".format(cutoff, target)

            for commit in repo.git.log(target, pretty="format:%H", reverse=True).split(
                "\n"
            ):
                if commit not in commits:
                    commits.append(commit)

    for commit in other_commits:
        if commit not in commits:
            commits.append(commit)

    if current_commit is not None and str(current_commit) not in commits:
        logging.debug("Adding current commit '{}'".format(str(current_commit)))
        commits.append(str(current_commit))

    if tags_only:
        tagged_commits = {str(x.commit) for x in repo.tags}
        commits = set(commits).intersection(tagged_commits)
        logging.debug("Sorting commits by tag name")
        commits = list(commits)
        commits.sort(key=lambda c: repo.git().describe(c))

    return commits


def get_parser(description, default_branches=dict()):
    parser = argparse.ArgumentParser(description=description)
    _add_logging_arguments(parser)
    _add_common_benchmark_arguments(parser, default_branches)
    return parser


_commits_args = (
    ["--commits"],
    {
        "default": "",
        "help": "A comma-separated list of commits to generate jobs before. If `--regression` is picked, the first of the list is considered the 'current' commit for determining any other commits to be also be submitted",
    },
)
_regression_args = (
    ["--regression"],
    {
        "action": "store_true",
        "default": False,
        "help": "Choose commits to test based on the current commit, previous, and last tag relative to the commit",
    },
)
_tags_only_args = (
    ["--tags-only"],
    {
        "action": "store_true",
        "default": False,
        "help": "Limit generated jobs to tagged commits",
    },
)


def add_gen_asv_parser(subparsers, func):
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
    gen_asv_parser.add_argument(*_commits_args[0], **_commits_args[1])
    gen_asv_parser.add_argument(*_regression_args[0], **_regression_args[1])
    gen_asv_parser.add_argument(*_tags_only_args[0], **_tags_only_args[1])
    gen_asv_parser.set_defaults(func=func)


def add_gen_jobs_parser(subparsers, func):
    gen_jobs_parser = subparsers.add_parser("generate-jobs", help="Generate jobs")
    gen_jobs_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Do all work except submitting the jobs to LAVA",
    )
    gen_jobs_parser.add_argument(*_commits_args[0], **_commits_args[1])
    gen_jobs_parser.add_argument(*_regression_args[0], **_regression_args[1])
    gen_jobs_parser.add_argument(*_tags_only_args[0], **_tags_only_args[1])
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
    gen_jobs_parser.set_defaults(func=func)


def add_regression_check_parser(subparsers, func):
    regression_parser = subparsers.add_parser(
        "regression",
        help="Check current commit for regressions against previous commits",
    )
    regression_parser.add_argument(*_commits_args[0], **_commits_args[1])
    regression_parser.set_defaults(func=func)
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


def _add_common_benchmark_arguments(parser, default_branches):
    parser.add_argument(
        "--repo-path",
        type=pathlib.Path,
        required=True,
        help="The path a local copy of the repo",
    )
    parser.add_argument(
        "--branches",
        # Cutoff from git merge-base origin/BRANCH origin/master,
        # for the master branch cutoff at the last time the branch
        # was forked
        default=default_branches,
        help="A comma-separated list of branches in the format NAME[:CUTOFF] to check",
    )


def _add_logging_arguments(parser):
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
