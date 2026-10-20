"""SQLite 存储与增量合并。

设计要点：
- jobs 一行 = 一个岗位；job_sources 一行 = 一个来源。
- 重复运行只更新 last_seen，不新增行。
- 跨源重复先按 job_key 精确匹配，再按公司+城市+标题/JD 模糊匹配。
- 抓取失败不会把岗位标 closed；只有截止日期过期才自动 closed。
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

try:
    from . import dedupe
except ImportError:  # python3 scripts/radar.py
    import dedupe

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    company_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    alias_json TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT UNIQUE NOT NULL,
    company_id TEXT NOT NULL,
    company_name TEXT,
    sub_company TEXT DEFAULT '',
    title TEXT,
    title_norm TEXT,
    job_category TEXT,
    city TEXT,
    location_raw TEXT,
    education TEXT,
    education_state TEXT,
    majors TEXT,
    major_state TEXT,
    headcount TEXT,
    salary TEXT,
    description TEXT,
    grad_year INTEGER,
    job_type TEXT,
    deadline TEXT,
    publish_date TEXT,
    base_hit INTEGER DEFAULT 0,
    is_operation INTEGER DEFAULT 0,
    recommendation TEXT,
    reasons_json TEXT DEFAULT '[]',
    source TEXT,
    source_type TEXT,
    source_job_id TEXT,
    url TEXT,
    apply_url TEXT,
    verification_status TEXT,
    first_seen TEXT,
    last_seen TEXT,
    status TEXT DEFAULT 'active',
    sources_json TEXT DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_jobs_company_city ON jobs(company_id, city);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen);
CREATE INDEX IF NOT EXISTS idx_jobs_deadline ON jobs(deadline);

CREATE TABLE IF NOT EXISTS job_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    source_job_id TEXT NOT NULL,
    source_type TEXT,
    url TEXT,
    first_seen TEXT,
    last_seen TEXT,
    raw_json TEXT,
    UNIQUE(source, source_job_id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT UNIQUE NOT NULL,
    source TEXT,
    source_event_id TEXT,
    event_type TEXT,
    school TEXT,
    title TEXT,
    company TEXT,
    organizer TEXT,
    event_date TEXT,
    deadline TEXT,
    location TEXT,
    url TEXT,
    apply_url TEXT,
    description TEXT,
    first_seen TEXT,
    last_seen TEXT,
    raw_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_date ON events(event_date);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT,
    finished_at TEXT,
    stats_json TEXT
);

CREATE TABLE IF NOT EXISTS duplicate_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id_a INTEGER,
    job_id_b INTEGER,
    reason TEXT,
    decision TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS feishu_synced (
    job_id INTEGER NOT NULL,
    table_id TEXT NOT NULL,
    record_id TEXT,
    synced_at TEXT,
    PRIMARY KEY(job_id, table_id)
);

CREATE TABLE IF NOT EXISTS feishu_company_synced (
    company_id TEXT NOT NULL,
    table_id TEXT NOT NULL,
    record_id TEXT,
    synced_at TEXT,
    PRIMARY KEY(company_id, table_id)
);
"""

VERIFICATION = {
    "scbdc": "platform_verified",
    "sicau": "school_verified",
    "ncss": "platform_verified",
    "iguopin": "platform_verified",
    "ats": "employer_verified",
    "official_ats": "employer_verified",
    "aggregator": "unverified",
    "manual": "unverified",
}


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return date.today().isoformat()


class Store:
    def __init__(self, db_path: str, alias_path: Optional[str] = None):
        self.db_path = os.path.expanduser(db_path)
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.resolver = dedupe.CompanyResolver(alias_path)

    def close(self):
        self.conn.close()

    # ---------------- 公司 ----------------
    def ensure_company(self, company_name: str) -> Tuple[str, str]:
        company_id, canonical = self.resolver.resolve(company_name)
        if canonical:
            self.conn.execute(
                "INSERT INTO companies(company_id, canonical_name) VALUES(?,?) "
                "ON CONFLICT(company_id) DO NOTHING",
                (company_id, canonical),
            )
        return company_id, canonical

    # ---------------- 岗位 ----------------
    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["reasons"] = json.loads(d.get("reasons_json") or "[]")
        d["sources"] = json.loads(d.get("sources_json") or "[]")
        return d

    def _find_fuzzy(self, job: dict) -> Optional[dict]:
        company_id, _ = self.resolver.resolve(job.get("company"))
        city = job.get("city") or ""
        if city:
            rows = self.conn.execute(
                "SELECT * FROM jobs WHERE company_id=? AND (city=? OR city='') "
                "AND status!='closed'",
                (company_id, city),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM jobs WHERE company_id=? AND status!='closed'",
                (company_id,),
            ).fetchall()
        best = None
        for row in rows:
            reason = dedupe.duplicate_reason(job, self._row_to_dict(row), self.resolver)
            if reason:
                best = (row, reason)
                break
        return best

    def upsert_job(self, job: dict, run_date: Optional[str] = None) -> Tuple[int, bool, bool]:
        """返回 (job_db_id, is_new, was_merged)。"""
        run_date = run_date or today_str()
        company_id, canonical = self.ensure_company(job.get("company", ""))
        job = dict(job)
        job["company_id"] = company_id
        display_company = job.get("company") or canonical
        if not str(job.get("source_job_id", "")).strip():
            import hashlib
            job["source_job_id"] = hashlib.sha1(
                (job.get("url") or f"{job.get('company')}|{job.get('title')}|{job.get('city')}").encode()
            ).hexdigest()[:16]
        key = dedupe.job_key(job, self.resolver)
        row = self.conn.execute("SELECT * FROM jobs WHERE job_key=?", (key,)).fetchone()
        merge_reason = ""
        fuzzy_id = None
        if row is None:
            fuzzy = self._find_fuzzy(job)
            if fuzzy:
                row, merge_reason = fuzzy
                fuzzy_id = int(row["id"])
        is_new = row is None
        if is_new:
            cur = self.conn.execute(
                """INSERT INTO jobs(
                    job_key, company_id, company_name, sub_company, title, title_norm,
                    job_category, city, location_raw, education, education_state,
                    majors, major_state, headcount, salary, description, grad_year,
                    job_type, deadline, publish_date, base_hit, is_operation,
                    recommendation, reasons_json, source, source_type, source_job_id,
                    url, apply_url, verification_status, first_seen, last_seen,
                    status, sources_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    key, company_id, display_company, job.get("sub_company", ""),
                    job.get("title", ""), dedupe.normalize_title(job.get("title", "")),
                    job.get("job_category", ""), job.get("city", ""),
                    job.get("location_raw", ""), job.get("education", ""),
                    job.get("education_state", ""), job.get("majors", ""),
                    job.get("major_state", ""), job.get("headcount", ""),
                    job.get("salary", ""), job.get("description", ""),
                    job.get("grad_year"), job.get("job_type", ""),
                    job.get("deadline"), job.get("publish_date", ""),
                    1 if job.get("base_hit") else 0,
                    1 if job.get("is_operation") else 0,
                    job.get("recommendation", ""),
                    json.dumps(job.get("reasons", []), ensure_ascii=False),
                    job.get("source", ""), job.get("source_type", ""),
                    str(job.get("source_job_id", "")), job.get("url", ""),
                    job.get("apply_url", ""),
                    VERIFICATION.get(job.get("source", ""), "unverified"),
                    run_date, run_date, "active", "[]",
                ),
            )
            job_id = int(cur.lastrowid)
        else:
            job_id = int(row["id"])
            existing = self._row_to_dict(row)
            updates = {}
            for field in (
                "company_name", "sub_company", "title", "title_norm",
                "job_category", "city", "location_raw", "education",
                "education_state", "majors", "major_state", "headcount",
                "salary", "description", "grad_year", "job_type", "deadline",
                "publish_date", "recommendation", "url", "apply_url",
                "source", "source_type",
            ):
                value = dedupe.pick_better(existing, job, field)
                if value not in (None, ""):
                    updates[field] = value
            updates["last_seen"] = run_date
            updates["status"] = "active"
            updates["base_hit"] = 1 if (existing.get("base_hit") or job.get("base_hit")) else 0
            updates["is_operation"] = 1 if (existing.get("is_operation") or job.get("is_operation")) else 0
            updates["title_norm"] = dedupe.normalize_title(updates.get("title", existing.get("title", "")))
            if job.get("source_job_id"):
                updates["source_job_id"] = str(job["source_job_id"])
            # 低优先级来源不覆盖高优先级来源的判定
            old_priority = dedupe.SOURCE_PRIORITY.get(existing.get("source", ""), 0)
            new_priority = dedupe.SOURCE_PRIORITY.get(job.get("source", ""), 0)
            if new_priority >= old_priority:
                updates["reasons_json"] = json.dumps(job.get("reasons", []), ensure_ascii=False)
            # 保留 first_seen 和原 job_key
            set_clause = ", ".join(f"{k}=?" for k in updates)
            self.conn.execute(
                f"UPDATE jobs SET {set_clause} WHERE id=?",
                list(updates.values()) + [job_id],
            )
            if merge_reason:
                self.conn.execute(
                    "INSERT INTO duplicate_reviews(job_id_a, job_id_b, reason, decision, created_at) "
                    "VALUES(?,?,?,?,?)",
                    (job_id, fuzzy_id or job_id, merge_reason, "merged", now_str()),
                )

        # 记录来源
        self.conn.execute(
            """INSERT INTO job_sources(job_id, source, source_job_id, source_type, url,
                                       first_seen, last_seen, raw_json)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(source, source_job_id) DO UPDATE SET
                 job_id=excluded.job_id, last_seen=excluded.last_seen, url=excluded.url""",
            (job_id, job.get("source", ""), str(job.get("source_job_id", "")),
             job.get("source_type", ""), job.get("url", ""), run_date, run_date,
             job.get("raw", "")),
        )
        self._refresh_sources(job_id)
        return job_id, is_new, bool(merge_reason or not is_new)

    def _refresh_sources(self, job_id: int):
        rows = self.conn.execute(
            "SELECT source, source_job_id, source_type, url, first_seen, last_seen "
            "FROM job_sources WHERE job_id=? ORDER BY last_seen DESC",
            (job_id,),
        ).fetchall()
        sources = [dict(r) for r in rows]
        self.conn.execute(
            "UPDATE jobs SET sources_json=? WHERE id=?",
            (json.dumps(sources, ensure_ascii=False), job_id),
        )

    # ---------------- 事件 ----------------
    def upsert_event(self, event: dict, run_date: Optional[str] = None) -> Tuple[int, bool]:
        run_date = run_date or today_str()
        event = dict(event)
        eid = str(event.get("source_event_id", ""))
        if not eid:
            import hashlib
            eid = hashlib.sha1(
                f"{event.get('source')}|{event.get('title')}|{event.get('event_date')}".encode()
            ).hexdigest()[:16]
        event_key = f"{event.get('source')}|{eid}"
        row = self.conn.execute("SELECT id FROM events WHERE event_key=?", (event_key,)).fetchone()
        is_new = row is None
        if is_new:
            cur = self.conn.execute(
                """INSERT INTO events(event_key, source, source_event_id, event_type, school,
                    title, company, organizer, event_date, deadline, location, url, apply_url,
                    description, first_seen, last_seen, raw_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event_key, event.get("source", ""), eid, event.get("event_type", ""),
                 event.get("school", ""), event.get("title", ""), event.get("company", ""),
                 event.get("organizer", ""), event.get("event_date", ""),
                 event.get("deadline", ""), event.get("location", ""), event.get("url", ""),
                 event.get("apply_url", ""), event.get("description", ""),
                 run_date, run_date, event.get("raw", "")),
            )
            event_id = int(cur.lastrowid)
        else:
            event_id = int(row["id"])
            self.conn.execute(
                """UPDATE events SET title=?, company=?, organizer=?, event_date=?, deadline=?,
                   location=?, url=?, apply_url=?, description=?, last_seen=?, raw_json=?
                   WHERE id=?""",
                (event.get("title", ""), event.get("company", ""), event.get("organizer", ""),
                 event.get("event_date", ""), event.get("deadline", ""), event.get("location", ""),
                 event.get("url", ""), event.get("apply_url", ""), event.get("description", ""),
                 run_date, event.get("raw", ""), event_id),
            )
        return event_id, is_new

    # ---------------- 运行统计 ----------------
    def start_run(self, run_id: str):
        self.conn.execute(
            "INSERT INTO runs(run_id, started_at, stats_json) VALUES(?,?,?)",
            (run_id, now_str(), "{}"),
        )
        self.conn.commit()

    def finish_run(self, run_id: str, stats: dict):
        self.conn.execute(
            "UPDATE runs SET finished_at=?, stats_json=? WHERE run_id=?",
            (now_str(), json.dumps(stats, ensure_ascii=False), run_id),
        )
        self.conn.commit()

    def is_feishu_synced(self, job_id: int, table_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM feishu_synced WHERE job_id=? AND table_id=?",
            (job_id, table_id),
        ).fetchone()
        return row is not None

    def mark_feishu_synced(self, job_id: int, table_id: str, record_id: str = ""):
        self.conn.execute(
            "INSERT INTO feishu_synced(job_id, table_id, record_id, synced_at) "
            "VALUES(?,?,?,?) ON CONFLICT(job_id, table_id) DO UPDATE SET "
            "record_id=excluded.record_id, synced_at=excluded.synced_at",
            (job_id, table_id, record_id, now_str()),
        )
        self.conn.commit()

    def is_company_synced(self, company_id: str, table_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM feishu_company_synced WHERE company_id=? AND table_id=?",
            (company_id, table_id),
        ).fetchone()
        return row is not None

    def mark_company_synced(self, company_id: str, table_id: str, record_id: str = ""):
        self.conn.execute(
            "INSERT INTO feishu_company_synced(company_id, table_id, record_id, synced_at) "
            "VALUES(?,?,?,?) ON CONFLICT(company_id, table_id) DO UPDATE SET "
            "record_id=excluded.record_id, synced_at=excluded.synced_at",
            (company_id, table_id, record_id, now_str()),
        )
        self.conn.commit()

    def latest_run_stats(self) -> Dict[str, dict]:
        row = self.conn.execute(
            "SELECT stats_json FROM runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return {}
        try:
            return json.loads(row["stats_json"] or "{}")
        except ValueError:
            return {}

    def close_expired(self, on_date: Optional[str] = None) -> int:
        on_date = on_date or today_str()
        cur = self.conn.execute(
            "UPDATE jobs SET status='closed' WHERE deadline IS NOT NULL AND deadline < ? "
            "AND status='active'",
            (on_date,),
        )
        self.conn.commit()
        return cur.rowcount

    # ---------------- 查询 ----------------
    def list_jobs(self, first_seen: Optional[str] = None,
                  recommendations: Optional[List[str]] = None) -> List[dict]:
        sql = "SELECT * FROM jobs WHERE 1=1"
        params: list = []
        if first_seen:
            sql += " AND first_seen=?"
            params.append(first_seen)
        if recommendations:
            sql += " AND recommendation IN (" + ",".join("?" for _ in recommendations) + ")"
            params.extend(recommendations)
        sql += " ORDER BY CASE recommendation WHEN '可投' THEN 0 WHEN '待核实' THEN 1 WHEN '异地' THEN 2 ELSE 3 END, deadline, id"
        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_events(self, upcoming: bool = True, limit: int = 100) -> List[dict]:
        sql = "SELECT * FROM events"
        params: list = []
        if upcoming:
            sql += " WHERE event_date >= ?"
            params.append(today_str())
        sql += " ORDER BY event_date ASC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def exclusion_counts(self, first_seen: Optional[str] = None) -> Dict[str, int]:
        sql = "SELECT reasons_json FROM jobs WHERE recommendation='不推荐'"
        params: list = []
        if first_seen:
            sql += " AND first_seen=?"
            params.append(first_seen)
        counts: Dict[str, int] = {}
        for row in self.conn.execute(sql, params).fetchall():
            for reason in json.loads(row["reasons_json"] or "[]"):
                key = reason.split("（")[0]
                counts[key] = counts.get(key, 0) + 1
        return counts

    def export_csv(self, path: str, first_seen: Optional[str] = None):
        jobs = self.list_jobs(first_seen=first_seen)
        path = os.path.expanduser(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fields = [
            "id", "company_name", "sub_company", "title", "job_category", "city",
            "education", "majors", "grad_year", "job_type", "deadline",
            "recommendation", "reasons_json", "source", "verification_status",
            "url", "apply_url", "first_seen", "last_seen", "status",
        ]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for job in jobs:
                row = dict(job)
                row["reasons_json"] = "；".join(job.get("reasons", []))
                writer.writerow(row)
        return path
