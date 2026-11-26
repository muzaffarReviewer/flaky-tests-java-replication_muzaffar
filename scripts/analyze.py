#!/usr/bin/env python3
"""Analyse all per-condition results.

Input : every tests.csv / runs.csv found under the given directory (one per condition).
Output: summary.csv, per_test.csv, summary.md, flaky_by_condition.png, all_tests.csv.gz

Definitions (state these in the paper):
  - failure      = test outcome 'fail' or 'error'; skipped tests are ignored.
  - flaky test   = in ONE condition, a test that both passed and failed across runs.
  - always-fail  = a test that failed in every run of every condition (not flaky; excluded).
  - baseline     = cpus 4, fixed order.
  - resource-affected test = a test with at least one failure whose failure count in a
    condition differs from the baseline at adjusted p < 0.05 (Fisher exact test,
    Benjamini-Hochberg correction across all comparisons).
"""
import glob
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from scipy.stats import fisher_exact

BASELINE = ("4", "fixed")


def bh_adjust(p):
    """Benjamini-Hochberg adjusted p-values (same order as input)."""
    n = len(p)
    order = sorted(range(n), key=lambda i: p[i])
    adj = [0.0] * n
    prev = 1.0
    for rank in range(n, 0, -1):
        i = order[rank - 1]
        prev = min(prev, p[i] * n / rank)
        adj[i] = prev
    return adj


def main(indir, outdir):
    os.makedirs(outdir, exist_ok=True)
    tfiles = glob.glob(os.path.join(indir, "**", "tests.csv"), recursive=True)
    rfiles = glob.glob(os.path.join(indir, "**", "runs.csv"), recursive=True)
    if not tfiles:
        print("no tests.csv found")
        return 1
    df = pd.concat([pd.read_csv(f, dtype={"cpus": str}) for f in tfiles], ignore_index=True)
    runs = pd.concat([pd.read_csv(f, dtype={"cpus": str}) for f in rfiles], ignore_index=True)
    df = df[df["status"] != "skip"].copy()
    df["fail"] = df["status"].isin(["fail", "error"]).astype(int)
    df["test_id"] = df["class"].astype(str) + "#" + df["test"].astype(str)
    # Several test cases can share one name inside a run (repeated/parameterised tests).
    # Count each test name ONCE per run: it failed in that run if any instance failed.
    df = (df.groupby(["project", "cpus", "order", "run", "test_id"], as_index=False)
            .agg(fail=("fail", "max")))

    # per test and condition: runs and failures
    g = (df.groupby(["project", "test_id", "cpus", "order"])
           .agg(n_runs=("fail", "size"), n_fail=("fail", "sum")).reset_index())
    g["flaky_here"] = (g["n_fail"] > 0) & (g["n_fail"] < g["n_runs"])

    # tests that failed in every run of every condition are deterministic failures
    tot = g.groupby(["project", "test_id"]).agg(r=("n_runs", "sum"), f=("n_fail", "sum")).reset_index()
    always = set(map(tuple, tot[(tot["f"] == tot["r"]) & (tot["r"] > 0)][["project", "test_id"]].values))
    g["always_fail"] = [(p, t) in always for p, t in zip(g["project"], g["test_id"])]
    g = g[~g["always_fail"]]

    # comparison with baseline (only tests that failed at least once somewhere)
    ever = g.groupby(["project", "test_id"])["n_fail"].sum()
    ever = set(ever[ever > 0].index)
    base = g[(g["cpus"] == BASELINE[0]) & (g["order"] == BASELINE[1])].set_index(["project", "test_id"])
    rows = []
    for _, r in g.iterrows():
        key = (r["project"], r["test_id"])
        if key not in ever or (r["cpus"], r["order"]) == BASELINE or key not in base.index:
            continue
        b = base.loc[key]
        table = [[r["n_fail"], r["n_runs"] - r["n_fail"]], [b["n_fail"], b["n_runs"] - b["n_fail"]]]
        p = fisher_exact(table)[1]
        rows.append({**r.to_dict(), "base_fail": b["n_fail"], "base_runs": b["n_runs"], "p": p})
    cmp_df = pd.DataFrame(rows)
    if len(cmp_df):
        cmp_df["p_adj"] = bh_adjust(cmp_df["p"].tolist())
        cmp_df["affected"] = cmp_df["p_adj"] < 0.05
    else:
        cmp_df = pd.DataFrame(columns=["project", "test_id", "cpus", "order", "p", "p_adj", "affected"])
    cmp_df.to_csv(os.path.join(outdir, "per_test.csv"), index=False)

    # summary table per project and condition
    s = (g.groupby(["project", "cpus", "order"])
           .agg(tests=("test_id", "nunique"), tests_with_failure=("n_fail", lambda x: int((x > 0).sum())),
                flaky_tests=("flaky_here", "sum"), runs_max=("n_runs", "max")).reset_index())
    aff = (cmp_df[cmp_df["affected"]].groupby(["project", "cpus", "order"]).size()
           .rename("affected_vs_baseline").reset_index()) if len(cmp_df) else pd.DataFrame(
        columns=["project", "cpus", "order", "affected_vs_baseline"])
    s = s.merge(aff, how="left", on=["project", "cpus", "order"]).fillna({"affected_vs_baseline": 0})
    rt = (runs.groupby(["project", "cpus", "order"])
              .agg(runs_logged=("run", "size"), runs_with_reports=("test_cases", lambda x: int((x > 0).sum())),
                   timeouts=("mvn_exit", lambda x: int((x == 124).sum()))).reset_index())
    # mean run time over runs that finished (timed-out runs excluded)
    sec = (runs[runs["mvn_exit"] != 124].groupby(["project", "cpus", "order"])["seconds"]
           .mean().rename("mean_seconds").reset_index())
    rt = rt.merge(sec, how="left", on=["project", "cpus", "order"])
    s = s.merge(rt, how="left", on=["project", "cpus", "order"])
    s["cpus"] = pd.Categorical(s["cpus"], ["4", "1", "0.5"], ordered=True)
    s = s.sort_values(["project", "order", "cpus"])
    s.to_csv(os.path.join(outdir, "summary.csv"), index=False)
    with open(os.path.join(outdir, "summary.md"), "w") as f:
        f.write(s.round(1).to_markdown(index=False) if hasattr(s, "to_markdown") else s.to_string(index=False))
    df.to_csv(os.path.join(outdir, "all_tests.csv.gz"), index=False)

    # ---- run-level comparisons with the baseline (Fisher exact, BH-adjusted) ----
    # (a) share of finished runs in which at least one (non-deterministic) test failed
    keep = [(p, t) not in always for p, t in zip(df["project"], df["test_id"])]
    rl = (df[keep].groupby(["project", "cpus", "order", "run"])["fail"].max()
          .rename("any_fail").reset_index()
          .groupby(["project", "cpus", "order"])
          .agg(runs_ok=("any_fail", "size"), runs_with_failure=("any_fail", "sum")).reset_index())
    # (b) share of started runs that hung and were killed by the timeout (exit 124)
    hg = (runs.groupby(["project", "cpus", "order"])
              .agg(runs_started=("run", "size"), runs_hung=("mvn_exit", lambda x: int((x == 124).sum()))).reset_index())

    def vs_baseline(tab, n, k):
        ps = []
        for _, r in tab.iterrows():
            b = tab[(tab["project"] == r["project"]) & (tab["cpus"] == BASELINE[0]) & (tab["order"] == BASELINE[1])]
            if (r["cpus"], r["order"]) == BASELINE or b.empty:
                ps.append(float("nan")); continue
            b = b.iloc[0]
            ps.append(fisher_exact([[r[k], r[n] - r[k]], [b[k], b[n] - b[k]]])[1])
        tab = tab.copy()
        tab["rate"] = tab[k] / tab[n]
        tab["p"] = ps
        idx = tab["p"].notna()
        tab.loc[idx, "p_adj"] = bh_adjust(tab.loc[idx, "p"].tolist())
        tab["cpus"] = pd.Categorical(tab["cpus"], ["4", "1", "0.5"], ordered=True)
        return tab.sort_values(["project", "order", "cpus"])

    vs_baseline(rl, "runs_ok", "runs_with_failure").to_csv(os.path.join(outdir, "run_level_failures.csv"), index=False)
    vs_baseline(hg, "runs_started", "runs_hung").to_csv(os.path.join(outdir, "run_level_hangs.csv"), index=False)

    # figure
    piv = s.assign(cond=s["cpus"].astype(str) + " CPU / " + s["order"]).pivot(
        index="project", columns="cond", values="flaky_tests")
    ax = piv.plot(kind="bar", figsize=(9, 4))
    ax.set_ylabel("Flaky tests (mixed pass/fail across runs)")
    ax.set_xlabel("")
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    plt.savefig(os.path.join(outdir, "flaky_by_condition.png"), dpi=200)
    print(s.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
