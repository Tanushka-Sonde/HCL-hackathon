"""Unusual-activity rules over query events and auth events (WP-7).

Each rule is a simple, explainable threshold (configurable in ``.env``):

BURST              > N queries by one user within 5 minutes
INJECTION_ATTEMPTS >= N blocked prompt-injection queries in 24 h
PII_FISHING        >= N user-role answers that needed masking in 24 h
FAILED_LOGINS      >= N failed logins for one username within 10 minutes
FORBIDDEN_ACCESS   >= N 403 responses for one user in 24 h
TOKEN_SPIKE        today's tokens > factor x the user's median daily tokens
                   (over the previous 7 days with usage), or above the cap
OFF_HOURS          queries between the configured local hours (low severity)
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.config import Settings

SEVERITY = {
    "BURST": "medium",
    "INJECTION_ATTEMPTS": "high",
    "PII_FISHING": "high",
    "FAILED_LOGINS": "high",
    "FORBIDDEN_ACCESS": "medium",
    "TOKEN_SPIKE": "medium",
    "OFF_HOURS": "low",
}


@dataclass
class _Hit:
    ts: datetime
    ref: str | None  # query ID for query events


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _max_in_window(hits: list[_Hit], window: timedelta) -> list[_Hit]:
    """The largest group of hits that fits inside one sliding window."""
    hits = sorted(hits, key=lambda h: h.ts)
    best: list[_Hit] = []
    start = 0
    for end in range(len(hits)):
        while hits[end].ts - hits[start].ts > window:
            start += 1
        if end - start + 1 > len(best):
            best = hits[start : end + 1]
    return best


def _finding(
    rule: str, who: dict[str, Any], hits: list[_Hit], window: str
) -> dict[str, Any]:
    return {
        "user_id": who.get("user_id"),
        "username": who.get("username"),
        "rule": rule,
        "severity": SEVERITY[rule],
        "count": len(hits),
        "window": window,
        "first_seen": min(h.ts for h in hits).isoformat(timespec="seconds"),
        "last_seen": max(h.ts for h in hits).isoformat(timespec="seconds"),
        "example_query_ids": [h.ref for h in hits if h.ref][:5],
    }


def detect_anomalies(
    events: list[dict[str, Any]],
    auth_events: list[dict[str, Any]],
    settings: Settings,
    *,
    since_hours: float = 24,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Findings whose most recent hit falls inside the last ``since_hours``.

    ``events`` should cover at least 8 days so TOKEN_SPIKE has a baseline.
    Evaluation runs are ignored (they are not user activity).
    """
    now = now or datetime.now(UTC)
    report_from = now - timedelta(hours=since_hours)
    day = timedelta(hours=24)
    findings: list[dict[str, Any]] = []

    by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    names: dict[str, str] = {}
    for e in events:
        ident = e["identity"]
        if e.get("eval") or not ident.get("user_id"):
            continue
        by_user[ident["user_id"]].append(e)
        names[ident["user_id"]] = ident.get("username") or ident["user_id"]

    for user_id, evs in by_user.items():
        who = {"user_id": user_id, "username": names[user_id]}
        hits = [
            _Hit(_parse(e["identity"]["timestamp"]), e["identity"]["query_id"])
            for e in evs
        ]
        recent = [h for h in hits if h.ts >= now - day]

        burst = _max_in_window(recent, timedelta(minutes=5))
        if len(burst) > settings.kis_anomaly_burst_per_5min:
            findings.append(_finding("BURST", who, burst, "5 min"))

        blocked = [
            h
            for h, e in zip(hits, evs, strict=True)
            if h.ts >= now - day and e["safety"].get("injection_blocked")
        ]
        if len(blocked) >= settings.kis_anomaly_injection_per_24h:
            findings.append(_finding("INJECTION_ATTEMPTS", who, blocked, "24 h"))

        masked = [
            h
            for h, e in zip(hits, evs, strict=True)
            if h.ts >= now - day
            and (e.get("masking") or {}).get("applied")
            and (e.get("masking") or {}).get("counts")
        ]
        if len(masked) >= settings.kis_anomaly_pii_per_24h:
            findings.append(_finding("PII_FISHING", who, masked, "24 h"))

        findings.extend(_token_spike(who, hits, evs, settings, now))

        start_h, end_h = settings.kis_off_hours_start, settings.kis_off_hours_end
        off = [h for h in recent if start_h <= h.ts.astimezone().hour < end_h]
        if off:
            findings.append(
                _finding(
                    "OFF_HOURS", who, off, f"{start_h:02d}:00-{end_h:02d}:00 local"
                )
            )

    failed: dict[str, list[_Hit]] = defaultdict(list)
    forbidden: dict[str, list[_Hit]] = defaultdict(list)
    auth_who: dict[str, dict[str, Any]] = {}
    for a in auth_events:
        ts = _parse(a["ts"])
        if ts < now - day:
            continue
        key = a.get("username") or a.get("user_id") or "unknown"
        auth_who[key] = {"user_id": a.get("user_id"), "username": a.get("username")}
        if a["event"] == "login_failed":
            failed[key].append(_Hit(ts, None))
        elif a["event"] == "forbidden":
            forbidden[key].append(_Hit(ts, None))
    for key, hits in failed.items():
        group = _max_in_window(hits, timedelta(minutes=10))
        if len(group) >= settings.kis_anomaly_failed_logins_10min:
            findings.append(_finding("FAILED_LOGINS", auth_who[key], group, "10 min"))
    for key, hits in forbidden.items():
        if len(hits) >= settings.kis_anomaly_forbidden_per_24h:
            findings.append(_finding("FORBIDDEN_ACCESS", auth_who[key], hits, "24 h"))

    findings = [f for f in findings if _parse(f["last_seen"]) >= report_from]
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order[f["severity"]], f["last_seen"]), reverse=False)
    return findings


def _token_spike(
    who: dict[str, Any],
    hits: list[_Hit],
    evs: list[dict[str, Any]],
    settings: Settings,
    now: datetime,
) -> list[dict[str, Any]]:
    daily: dict[str, int] = defaultdict(int)
    today = now.date().isoformat()
    today_hits = []
    for hit, e in zip(hits, evs, strict=True):
        usage = e.get("usage") or {}
        tokens = (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
        key = hit.ts.date().isoformat()
        daily[key] += tokens
        if key == today and tokens:
            today_hits.append(hit)
    used_today = daily.get(today, 0)
    if not used_today:
        return []
    window_start = (now - timedelta(days=7)).date().isoformat()
    history = [v for k, v in daily.items() if window_start <= k < today and v]
    over_cap = used_today > settings.kis_user_daily_token_cap
    spike = len(
        history
    ) >= 3 and used_today > settings.kis_anomaly_token_spike_factor * statistics.median(
        history
    )
    if not (over_cap or spike):
        return []
    finding = _finding("TOKEN_SPIKE", who, today_hits, "today")
    finding["count"] = used_today
    finding["detail"] = (
        f"{used_today} tokens today; daily cap {settings.kis_user_daily_token_cap}"
        if over_cap
        else f"{used_today} tokens today vs median {int(statistics.median(history))}"
    )
    return [finding]
