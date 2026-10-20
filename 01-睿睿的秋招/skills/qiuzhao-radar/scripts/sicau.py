"""四川农业大学就业信息网适配器（直连公开 JSON API）。

这是成都高校里少数不需要登录、直接返回 JSON 的站点，作为
“学校直连”示例保留；其他学校的直连入口多数有 WAF/登录态，
先由川e就平台统一覆盖。
"""
from __future__ import annotations

import html
import json
import re
from typing import List

try:
    from . import net
except ImportError:  # python3 scripts/radar.py
    import net

BASE = "https://job.sicau.edu.cn"
SOURCE = "sicau"
SCHOOL = "四川农业大学"


def clean(value: str) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _get(path: str, page_no: int, page_size: int) -> dict:
    url = f"{BASE}{path}?pageNo={page_no}&pageSize={page_size}&schoolBranch="
    data = json.loads(net.get(url, headers={"Accept": "application/json"}))
    if not data.get("success", False):
        raise net.HttpError(f"川农接口返回失败：{data.get('message')}")
    return data


def fetch_recruitments(page_no: int = 1, page_size: int = 50) -> List[dict]:
    data = _get("/job/website/recruitmentList", page_no, page_size)
    events = []
    for item in data.get("data", []):
        rid = item.get("recruitmentId", "")
        poster = item.get("posterId", "")
        url = (
            f"{BASE}/employment/zpxx/xyxjh/meeting_details/index.html"
            f"?id={rid}&postid={poster}"
        )
        begin = (item.get("beginDate") or "")[:10]
        events.append({
            "source": SOURCE,
            "source_type": "school_official",
            "source_event_id": f"recruitment:{rid}",
            "event_type": "teachin",
            "school": SCHOOL,
            "title": clean(item.get("title", "")),
            "company": clean(item.get("entName", "")),
            "organizer": clean(item.get("entName", "")) or SCHOOL,
            "event_date": begin,
            "deadline": (item.get("enrollEndDate") or "")[:10],
            "location": clean(item.get("place", "")),
            "url": url,
            "apply_url": url,
            "description": clean(item.get("description", "")),
            "email": item.get("entEmail", ""),
            "homepage": item.get("entHomepage", ""),
            "address": clean(item.get("entAddress", "")),
            "company_type": item.get("entAttribute", ""),
            "can_apply": bool(item.get("canApply")),
            "is_expired": bool(item.get("isExpired")),
            "raw": json.dumps(item, ensure_ascii=False),
        })
    return events


def fetch_jobfairs(page_no: int = 1, page_size: int = 50) -> List[dict]:
    data = _get("/job/website/bigMeetingRecruitList", page_no, page_size)
    events = []
    for item in data.get("data", []):
        mid = item.get("bigMeetingRecruitId", "")
        poster = item.get("posterId", "")
        url = (
            f"{BASE}/employment/zpxx/xyzph/xyzph_info/index.html"
            f"?id={mid}&postid={poster}"
        )
        begin = (item.get("beginDate") or "")[:10]
        events.append({
            "source": SOURCE,
            "source_type": "school_official",
            "source_event_id": f"jobfair:{mid}",
            "event_type": "jobfair",
            "school": SCHOOL,
            "title": clean(item.get("title", "")),
            "company": "",
            "organizer": SCHOOL,
            "event_date": begin,
            "deadline": (item.get("enrollEndDate") or "")[:10],
            "location": clean(item.get("address", "")),
            "url": url,
            "apply_url": url,
            "description": clean(item.get("content", "")),
            "can_apply": bool(item.get("canApply")),
            "is_expired": bool(item.get("isExpired")),
            "raw": json.dumps(item, ensure_ascii=False),
        })
    return events


def fetch_events(max_pages: int = 1, page_size: int = 50) -> List[dict]:
    out: List[dict] = []
    for page in range(1, max_pages + 1):
        try:
            out.extend(fetch_recruitments(page, page_size))
            out.extend(fetch_jobfairs(page, page_size))
        except net.HttpError:
            break
    return out
