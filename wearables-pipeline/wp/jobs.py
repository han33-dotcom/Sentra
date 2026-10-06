"""Processing jobs shared by the CLI, the Windows scheduled task and the Docker worker."""
import pandas as pd

from . import config, db


def process(source="live", age_overrides=None, log=print, charts=True):
    """Stage 2 on the Kaggle dataset or on our live database. Returns the output folder."""
    from .process import pipeline

    ages = {}
    if source == "kaggle":
        obs = pd.read_parquet(config.DATA_DIR / "canonical" / "kaggle_fitbit_observations.parquet")
    else:
        with db.session() as con:
            obs = pd.read_sql("SELECT * FROM observations", con)
            label_to_sid = dict(con.execute("SELECT label, subject_id FROM accounts").fetchall())
            ages = {sid: age for sid, age in con.execute("SELECT subject_id, age FROM accounts WHERE age IS NOT NULL")}
        for label, years in (age_overrides or {}).items():
            if label in label_to_sid:
                ages[label_to_sid[label]] = int(years)
    if obs.empty:
        log("no observations yet - nothing to process")
        return None
    out = config.DATA_DIR / "processed" / source
    g, d, c, clean_obs = pipeline.run(obs, out, ages, log=log)
    if charts:
        from . import report
        files = report.build(g, d, c, config.REPORTS_DIR / source, clean_obs)
        log("charts: " + ", ".join(str(f) for f in files))
    return out
