"""Google Health API data point  ->  canonical observation rows / session rows.

Field names follow the DataPoint reference. Anything we don't map explicitly is still
kept: raw JSON is always stored, and numeric fields of daily types are flattened generically.
"""
import json

from ..canonical import SLEEP_STAGE, unit
from .google_health import camel

SOURCE = "google_health"


def offset_min(s):
    """'10800s' -> 180"""
    if not s:
        return None
    try:
        return int(float(str(s).rstrip("s")) // 60)
    except ValueError:
        return None


def _device(dp):
    ds = dp.get("dataSource", {}) or {}
    dev = ds.get("device") or {}
    name = dev.get("displayName") or dev.get("model") or ds.get("platform")
    return name, ("manual" if ds.get("recordingMethod") == "MANUAL" else "auto")


def record_key(dt: str, dp: dict) -> str:
    """Stable id for a data point. Most points (heart rate, steps, daily metrics) come WITHOUT a
    `name`, so build one from type + recording method + device + time. Re-fetching the same
    record gives the same key -> it overwrites instead of duplicating (Fitbit revises recent days)."""
    if dp.get("name") and not dp["name"].endswith("/"):
        return dp["name"]
    body = dp.get(camel(dt)) or {}
    ds = dp.get("dataSource") or {}
    tag = f"{dt}|{ds.get('recordingMethod', '')}|{(ds.get('device') or {}).get('displayName', '')}"
    iv, st, d = body.get("interval") or {}, body.get("sampleTime") or {}, body.get("date")
    if iv.get("startTime"):
        return f"{tag}|{iv['startTime']}"
    if st.get("physicalTime"):
        return f"{tag}|{st['physicalTime']}"
    if d:
        return f"{tag}|{d['year']:04d}-{d['month']:02d}-{d['day']:02d}"
    return f"{tag}|" + json.dumps(body, sort_keys=True)


def _row(subject, dp, metric, value, start, end, off, resolution, key):
    device, method = _device(dp)
    return dict(subject_id=subject, source=SOURCE, device=device, metric=metric, value=float(value),
                unit=unit(metric), start_utc=start, end_utc=end, utc_offset_min=off,
                resolution=resolution, method=method, quality_flag="ok", raw_ref=key)


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f   # drop NaN ("NaN" strings appear in temperature data)


def _date_iso(d):
    return f"{d['year']:04d}-{d['month']:02d}-{d['day']:02d}T00:00:00Z"


def _sleep_code(stage_type: str):
    t = (stage_type or "").lower()
    for k in ("awake", "light", "deep", "rem", "restless"):
        if k in t:
            return SLEEP_STAGE[k]
    return SLEEP_STAGE["asleep_unspecified"]


def _flatten_numbers(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("date",):
                continue
            yield from _flatten_numbers(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield prefix, obj
    elif isinstance(obj, str):
        try:
            yield prefix, float(obj)
        except ValueError:
            pass


def map_point(subject: str, dt: str, dp: dict):
    """Returns (observation_rows, session_row_or_None)."""
    body = dp.get(camel(dt), {})
    rows, sess = [], None
    key = record_key(dt, dp)

    def row(*a):
        return _row(subject, dp, *a, key)

    if dt in ("heart-rate", "heart-rate-variability", "oxygen-saturation", "respiratory-rate-sleep-summary"):
        st = body.get("sampleTime", {})
        metric, val = {
            "heart-rate": ("heart_rate", body.get("beatsPerMinute")),
            "heart-rate-variability": ("hrv_rmssd", body.get("rootMeanSquareOfSuccessiveDifferencesMilliseconds")),
            "oxygen-saturation": ("spo2", body.get("percentage")),
            "respiratory-rate-sleep-summary": ("sleep_respiratory_rate", (body.get("fullSleepStats") or {}).get("breathsPerMinute")),
        }[dt]
        if val is None:  # unknown field name -> first numeric leaf
            val = next((v for k, v in _flatten_numbers(body) if "sampleTime" not in k), None)
        if _num(val) is not None:
            rows.append(row(metric, val, st.get("physicalTime"), None,
                             offset_min(st.get("utcOffset")), "sample"))

    elif dt in ("steps", "active-zone-minutes", "sedentary-period", "activity-level"):
        iv = body.get("interval", {})
        s, e = iv.get("startTime"), iv.get("endTime")
        off = offset_min(iv.get("startUtcOffset"))
        if dt == "steps":
            rows.append(row("steps", body.get("count", 0), s, e, off, "interval"))
        elif dt == "sedentary-period":
            from datetime import datetime
            mins = (datetime.fromisoformat(e.replace("Z", "+00:00")) - datetime.fromisoformat(s.replace("Z", "+00:00"))).total_seconds() / 60
            rows.append(row("sedentary_minutes", mins, s, e, off, "interval"))
        elif dt == "active-zone-minutes":
            val = next((v for k, v in _flatten_numbers(body) if "interval" not in k and "Offset" not in k), 1)
            rows.append(row("active_zone_minutes", val, s, e, off, "interval"))
        # activity-level: kept raw only for now (categorical)

    elif dt.startswith("daily-"):
        d = body.get("date")
        if d:
            start = _date_iso(d)
            named = {
                "daily-resting-heart-rate": [("resting_heart_rate", body.get("beatsPerMinute"))],
                "daily-heart-rate-variability": [
                    ("daily_hrv_rmssd", body.get("averageHeartRateVariabilityMilliseconds")),
                    ("daily_hrv_deep_rmssd", body.get("deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds")),
                    ("daily_nonrem_hr", body.get("nonRemHeartRateBeatsPerMinute"))],
                "daily-respiratory-rate": [("daily_respiratory_rate", body.get("breathsPerMinute"))],
                "daily-sleep-temperature-derivations": [("nightly_skin_temp_c", body.get("nightlyTemperatureCelsius"))],
            }.get(dt)
            if named:
                for m, v in named:
                    if _num(v) is not None:
                        rows.append(row(m, v, start, None, None, "daily"))
            else:  # respiratory rate, SpO2 ... -> keep every numeric field
                for path, v in _flatten_numbers(body):
                    if _num(v) is None:
                        continue
                    rows.append(row(f"{dt.replace('-', '_')}.{path}", v, start, None, None, "daily"))

    elif dt in ("sleep", "exercise"):
        iv = body.get("interval", {})
        off = offset_min(iv.get("startUtcOffset"))
        detail = {k: body.get(k) for k in ("type", "metadata", "summary", "exerciseType", "metricsSummary", "activeDuration")
                  if body.get(k) is not None}
        sess = dict(raw_ref=key, subject_id=subject, kind=dt, start_utc=iv.get("startTime"),
                    end_utc=iv.get("endTime"), utc_offset_min=off, detail=json.dumps(detail))
        if dt == "sleep":
            for stg in body.get("stages", []):
                rows.append(row("sleep_stage", _sleep_code(stg.get("type")),
                                 stg.get("startTime"), stg.get("endTime"),
                                 offset_min(stg.get("startUtcOffset")) if stg.get("startUtcOffset") else off, "interval"))
    return [r for r in rows if r["start_utc"]], sess
