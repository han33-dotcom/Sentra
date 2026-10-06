"""Four PNG charts that show what each processing stage produces."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
BLUE, ORANGE = "#2a78d6", "#eb6834"
STATUS = {"green": "#0ca30c", "amber": "#fab219", "red": "#d03b3b"}
SEQ = LinearSegmentedColormap.from_list("blue", ["#eef4fd", "#86b6ef", "#2a78d6", "#104281"])

plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "text.color": INK, "font.size": 10,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.8, "axes.titleweight": "bold", "axes.titlesize": 12, "axes.titlelocation": "left",
})


def _save(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def completeness(g, out):
    w = g.assign(date=g.minute.dt.normalize()).groupby(["subject_id", "date"]).worn.sum().div(60).unstack(fill_value=0)
    w = w.loc[w.sum(axis=1).sort_values(ascending=False).index]
    w = w[w.sum(axis=1) > 0]
    w = w.loc[:, w.columns >= w.columns[(w.sum(axis=0) > 0).values.argmax()]]   # start at the first day with data
    fig, ax = plt.subplots(figsize=(10, 0.28 * len(w) + 1.6))
    im = ax.imshow(w.values, aspect="auto", cmap=SEQ, vmin=0, vmax=24, interpolation="nearest")
    ax.set_yticks(range(len(w)), [s[-4:] for s in w.index], fontsize=7)
    idx = np.arange(0, w.shape[1], 7)
    ax.set_xticks(idx, [w.columns[i].strftime("%b %d") for i in idx])
    ax.grid(False)
    ax.set_title(f"Data completeness: hours of heart-rate data per person per day ({len(w)} people with HR)")
    ax.set_ylabel("subject (last 4 chars)")
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.01)
    cb.set_label("hours worn", color=INK2)
    return _save(fig, out / "1_completeness.png")


def subject_days(g, d, sid, out, days=3):
    s = g[g.subject_id == sid]
    worn_per_day = s.groupby(s.minute.dt.normalize()).worn.sum()
    full = worn_per_day[worn_per_day >= 1000].index
    start = full[min(7, max(0, len(full) - days))] if len(full) else s[s.worn].minute.min().normalize()
    s = s[(s.minute >= start) & (s.minute < start + pd.Timedelta(days=days))]
    fig, ax = plt.subplots(figsize=(11, 3.6))
    asleep = s.asleep.values
    for i0, i1 in _runs(asleep):
        ax.axvspan(s.minute.iloc[i0], s.minute.iloc[i1], color=BLUE, alpha=0.10, lw=0)
    ax.plot(s.minute, s.hr_mean, color=ORANGE, lw=1.0)
    lim = d[d.subject_id == sid].hr_limit_bpm.iloc[0]
    ax.axhline(lim, color=INK2, lw=1, ls="--")
    ax.text(s.minute.iloc[-1], lim + 2, f"sustained-HR limit {lim:.0f} bpm (placeholder)", ha="right", color=INK2, fontsize=8)
    ax.set_title(f"One person, {days} days at 1-minute resolution: heart rate with sleep shaded")
    ax.set_ylabel("heart rate (bpm)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %H:%M"))
    return _save(fig, out / "2_one_person_minutes.png")


def _runs(mask):
    runs, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        if not v and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(mask) - 1))
    return runs


def recovery_chart(d, sid, out):
    """Three stacked panels, one measure each, same date axis: sleep, resting HR, HRV vs own baseline."""
    x = d[(d.subject_id == sid) & d.usable_day].sort_values("date")
    panels = [("sleep_min", "sleep (h)", 1 / 60, "flag_short_sleep"), ("rhr", "resting HR (bpm)", 1, "flag_rhr_up"),
              ("daily_hrv_rmssd", "HRV RMSSD (ms)", 1, "flag_hrv_down")]
    panels = [p for p in panels if p[0] in x and x[p[0]].notna().any()]
    fig, axes = plt.subplots(len(panels), 1, figsize=(10, 2.3 * len(panels) + 0.6), sharex=True)
    axes = np.atleast_1d(axes)
    for ax, (col, label, k, flag) in zip(axes, panels, strict=True):
        ax.plot(x.date, x[col] * k, color=BLUE, lw=1.8, marker="o", ms=3.5)
        if f"{col}_base" in x:
            ax.plot(x.date, x[f"{col}_base"] * k, color=INK2, lw=1.2, ls="--")
        if col == "sleep_min":
            ax.axhline(360 / 60, color=STATUS["amber"], lw=1)
        hit = x[x[flag].fillna(False).astype(bool)]
        ax.scatter(hit.date, hit[col] * k, s=80, facecolor="none", edgecolor=STATUS["red"], lw=1.8, zorder=5)
        ax.set_ylabel(label)
    axes[0].set_title("Recovery signals vs own baseline (dashed = 28-day median, circles = flagged nights)")
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    return _save(fig, out / "3_recovery_vs_baseline.png")


def coverage_chart(obs, out):
    """Which data we actually hold, per data type per day - shows extraction gaps at a glance."""
    o = obs.assign(day=obs.t.dt.normalize())
    groups = {"heart rate (1-s)": "heart_rate", "steps": "steps", "sleep stages": "sleep_stage",
              "HRV samples": "hrv_rmssd", "resting HR (daily)": "resting_heart_rate", "HRV (daily)": "daily_hrv_rmssd"}
    rows = {k: o[o.metric == m].groupby("day").size() for k, m in groups.items() if (o.metric == m).any()}
    days = pd.date_range(o.day.min(), o.day.max())
    M = pd.DataFrame({k: v.reindex(days, fill_value=0) for k, v in rows.items()}).T.gt(0).astype(int)
    fig, ax = plt.subplots(figsize=(10, 0.45 * len(M) + 1.4))
    ax.imshow(M.values, aspect="auto", cmap=LinearSegmentedColormap.from_list("c", [GRID, BLUE]), vmin=0, vmax=1,
              interpolation="nearest")
    ax.set_yticks(range(len(M)), M.index)
    idx = np.arange(0, len(days), 7)
    ax.set_xticks(idx, [days[i].strftime("%b %d") for i in idx])
    ax.grid(False)
    ax.set_title("What we hold: days with data, per data type (blue = present)")
    return _save(fig, out / "0_coverage.png")


def baseline_chart(d, sid, out):
    x = d[(d.subject_id == sid) & d.valid_day].sort_values("date")
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.plot(x.date, x.rhr_base, color=INK2, lw=1.5, label="personal baseline (28-day median)")
    ax.plot(x.date, x.rhr, color=BLUE, lw=2, marker="o", ms=4, label="resting HR (estimated)")
    hit = x[x.flag_rhr_up]
    ax.scatter(hit.date, hit.rhr, s=90, facecolor="none", edgecolor=STATUS["red"], lw=2, zorder=5,
               label="flag: >= 2 robust SD above own baseline")
    ax.set_title("Resting heart rate vs the person's own baseline")
    ax.set_ylabel("bpm")
    ax.legend(frameon=False, loc="upper left", fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    return _save(fig, out / "3_baseline_one_person.png")


def cohort_chart(c, out):
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ok = c[~c.suppressed]
    ax.bar(ok.date, ok.pct_fatigue_amber_or_red * 100, width=0.8, color=STATUS["amber"], label="amber or red fatigue")
    sup = c[c.suppressed]
    ax.scatter(sup.date, np.zeros(len(sup)) + 0.5, marker="x", color=INK2, label="hidden: fewer than 5 people")
    ax.set_title("What the HSE manager sees: share of workers with fatigue signs, per day")
    ax.set_ylabel("% of workers with valid data")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    return _save(fig, out / "4_cohort_view.png")


def build(g, d, c, out, obs=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    # pick the person with the most usable days for the single-person charts
    sid = d[d.usable_day].subject_id.value_counts().index[0]
    charts = []
    if obs is not None:
        charts.append(coverage_chart(obs, out))
    charts += [completeness(g, out), subject_days(g, d, sid, out), recovery_chart(d, sid, out)]
    if (~c.suppressed).any():          # the group view needs >= k people
        charts.append(cohort_chart(c, out))
    return charts
