# Do Hardware Conditions Make Software Tests Flaky? A Small Java Replication

Reproducibility package for a student research paper (Architecture of Computers, Student Research Challenge 2026/27).

## Question
On a small set of open-source Java projects, do restricted CPU resources and shuffled test-class order change how often tests fail without any code change, in line with the findings of Silva et al., "The Effects of Computational Resources on Flaky Tests"?

## Design
- **Projects (pinned commits, see `projects.csv`):** java-websocket, commons-exec, delight-nashorn-sandbox, logback-core. All four also appear in the 30 Java projects of Silva et al.; the commits here are recent ones, not the ones used by that study.
- **CPU conditions:** 4, 1 and 0.5 CPUs, set with Docker `--cpus` (CFS quota). Memory, disk and network are not restricted.
- **Order conditions:** `fixed` (Surefire `runOrder=alphabetical`) and `random` (Surefire `runOrder=random`, seeds 1001, 1002, ...). The same seeds are used in every CPU condition.
- **Baseline:** 4 CPUs, fixed order.
- **Runs:** the number of runs per condition is set when the workflow is started (see the paper for the value that was used).
- **Metric:** failure count per test per condition. A *flaky* test is a test that both passed and failed in the runs of one condition. A test that failed in every run of every condition is a deterministic failure and is excluded.
- **Statistics:** Fisher exact test of each test's failure count against the baseline, with Benjamini-Hochberg correction. (Silva et al. used a chi-squared test.)

## How to run
1. Fork or upload this repository to GitHub (public). Put `experiment.yml` at `.github/workflows/experiment.yml`.
2. Open the **Actions** tab, choose **flaky-test-experiment**, click **Run workflow**, and set the number of runs and the time budget.
3. When it finishes, download the `analysis` artifact (summary tables, per-test results, figure) and the `results-*` artifacts (raw per-run data and logs).

To run one condition locally (needs Docker): `bash scripts/run_condition.sh java-websocket 0.5 random 20 120`

## Known limitations
- GitHub-hosted runners are shared virtual machines. Their timing noise is not controlled, and a "4 CPU" baseline is a 4-vCPU VM, not dedicated hardware.
- Random order shuffles test **classes** only (Surefire). Test methods inside a class keep their order.
- Projects were tested at recent commits, so results are not directly comparable with the original study.
- Only CPU was restricted. Memory, disk and network effects are not studied.
- The number of runs limits which rarely failing tests can be detected.

## AI-use declaration
The author (Muzaffar Yuldoshev, ID 68777) used Claude (Anthropic) to help plan the experiment, write and debug the GitHub Actions workflow and the shell and Python scripts in this repository, analyse the results, and draft the paper. The author ran the experiments, tested the code and checked the reported results, and is responsible for all content.
