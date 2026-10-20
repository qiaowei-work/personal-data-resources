"""国家大学生就业服务平台（ncss.cn）适配器。

公开匿名接口，每次查询最多返回 100 条；这里按单位性质分组抓取，
作为“学校/省级平台”之外的全国校招补充源。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List
from urllib.parse import urlencode

try:
    from . import net
except ImportError:  # python3 scripts/radar.py
    import net

API = "https://www.ncss.cn/student/jobs/jobslist/ajax/"
SOURCE = "ncss"
TZ_CN = timezone(timedelta(hours=8))
DEFAULT_PROPERTIES = ["国有企业", "机关/事业单位/非营利机构", "民营企业", "外商投资企业"]


def _ms_to_date(ms) -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=TZ_CN).strftime("%Y-%m-%d")
    except Exception:
        return ""


def fetch_page(prop: str, offset: int, limit: int = 20) -> List[dict]:
    qs = {
        "jobType": "", "areaCode": "", "jobName": "", "monthPay": "",
        "industrySectors": "", "property": prop, "categoryCode": "",
        "memberLevel": "", "recruitType": "", "offset": offset,
        "limit": limit, "keyUnits": "", "degreeCode": "",
        "sourcesName": "0", "sourcesType": "",
    }
    url = API + "?" + urlencode(qs)
    try:
        data = json.loads(net.get(url, headers={"Accept": "application/json"}))
    except Exception:
        return []
    if not data.get("flag"):
        return []
    return (data.get("data") or {}).get("list") or []


def fetch_jobs(properties: Iterable[str] = None, max_pages: int = 5,
               page_size: int = 20, delay: float = 0.4) -> List[dict]:
    properties = list(properties or DEFAULT_PROPERTIES)
    limiter = net.RateLimiter(delay)
    seen = {}
    for prop in properties:
        empty_streak = 0
        for page in range(1, max_pages + 1):
            limiter.wait()
            items = fetch_page(prop, page, page_size)
            if not items:
                empty_streak += 1
                if empty_streak >= 2:
                    break
                continue
            empty_streak = 0
            for item in items:
                jid = item.get("jobId")
                if jid:
                    seen[jid] = item
            if len(items) < page_size:
                break
    return list(seen.values())


def _salary(item: dict) -> str:
    low = item.get("lowMonthPay")
    high = item.get("highMonthPay")
    try:
        low_f, high_f = float(low), float(high)
    except (TypeError, ValueError):
        return ""
    if low_f <= 0 and high_f <= 0:
        return ""
    if high_f <= 100:
        return f"{low_f:g}-{high_f:g}K"
    return f"{low_f:g}-{high_f:g}"


def to_record(item: dict) -> dict:
    return {
        "source": SOURCE,
        "source_type": "official_platform",
        "source_job_id": str(item.get("jobId", "")),
        "company": (item.get("recName") or "").strip(),
        "company_type": (item.get("recProperty") or "").strip(),
        "title": (item.get("jobName") or "").strip(),
        "city": (item.get("areaCodeName") or "").strip(),
        "education": (item.get("degreeName") or "").strip(),
        "majors": (item.get("major") or "").strip(),
        "headcount": item.get("headCount"),
        "salary": _salary(item),
        "description": "",
        "publish_date": _ms_to_date(item.get("publishDate")),
        "deadline": "",
        "url": f"https://www.ncss.cn/student/jobs/{item.get('jobId')}/detail.html",
        "apply_url": f"https://www.ncss.cn/student/jobs/{item.get('jobId')}/detail.html",
        "raw": json.dumps(item, ensure_ascii=False),
    }
