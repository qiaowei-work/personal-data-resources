"""国聘网适配器（公开推荐池接口）。

当前只用 `/api/jobs/v1/recom-job` 的公开推荐池（约 400 条）。
国聘的完整搜索接口需要登录态/签名，暂不做；需要全量时用登录态浏览器。
"""
from __future__ import annotations

import json
from typing import List

try:
    from . import net
except ImportError:  # python3 scripts/radar.py
    import net

API = "https://gp-api.iguopin.com/api/jobs/v1/recom-job"
SOURCE = "iguopin"
REFERER = "https://www.iguopin.com/job/list"
RECOM = {"update_time": True, "company_nature": True, "hot_job": True}


def fetch_page(page: int, page_size: int = 20) -> List[dict]:
    payload = {"search": {"page": page, "page_size": page_size}, "recom": RECOM}
    try:
        body = net.post_json(
            API, payload,
            headers={"Referer": REFERER, "Accept": "application/json"},
        )
        data = json.loads(body)
    except Exception:
        return []
    return (data.get("data") or {}).get("list") or []


def fetch_jobs(max_pages: int = 20, page_size: int = 20,
               campus_only: bool = True, delay: float = 0.35) -> List[dict]:
    limiter = net.RateLimiter(delay)
    seen = {}
    for page in range(1, max_pages + 1):
        limiter.wait()
        items = fetch_page(page, page_size)
        if not items:
            break
        for item in items:
            jid = item.get("job_id")
            if not jid:
                continue
            if campus_only and "社会" in (item.get("recruitment_type_cn") or ""):
                continue
            seen[jid] = item
        if len(items) < page_size:
            break
    return list(seen.values())


def extract_city(district_list) -> str:
    if not district_list:
        return ""
    area = district_list[0].get("area_cn") or ""
    parts = [p for p in area.split("-") if p and p != "中国"]
    if not parts:
        return ""
    last = parts[-1]
    # “北京市-大兴区”要取北京，不是大兴；“四川省-成都市”取成都
    if len(parts) >= 2 and last.endswith(("区", "县", "旗")):
        return parts[-2].replace("市", "")
    return last.replace("市", "")


def _salary(item: dict) -> str:
    low = item.get("min_wage")
    high = item.get("max_wage")
    try:
        low_f, high_f = float(low), float(high)
    except (TypeError, ValueError):
        return ""
    if low_f <= 0 and high_f <= 0:
        return ""
    unit = item.get("wage_unit_cn") or ""
    return f"{low_f:g}-{high_f:g}{unit}"


def to_record(item: dict) -> dict:
    company = (item.get("company_name") or "").strip()
    department = (item.get("department_cn") or "").strip()
    if department == company:
        department = ""
    rt = item.get("recruitment_type_cn") or ""
    if "校园" in rt:
        job_type = "校招"
    elif "实习" in rt:
        job_type = "实习"
    elif "社会" in rt:
        job_type = "社招"
    else:
        job_type = ""
    company_info = item.get("company_info") or {}
    majors = "、".join(item.get("major_cn") or [])
    return {
        "source": SOURCE,
        "source_type": "official_platform",
        "source_job_id": str(item.get("job_id", "")),
        "company": company,
        "company_type": (company_info.get("nature_cn") or item.get("nature_cn") or "").strip(),
        "sub_company": department,
        "title": (item.get("job_name") or "").strip(),
        "city": extract_city(item.get("district_list")),
        "education": (item.get("education_cn") or "").strip(),
        "majors": majors,
        "headcount": item.get("amount"),
        "salary": _salary(item),
        "description": (item.get("contents") or "").strip(),
        "job_category": (item.get("category_cn") or "").strip(),
        "job_type": job_type,
        "publish_date": (item.get("start_time") or "")[:10],
        "deadline": (item.get("end_time") or "")[:10],
        "url": f"https://www.iguopin.com/job/detail?id={item.get('job_id')}",
        "apply_url": f"https://www.iguopin.com/job/detail?id={item.get('job_id')}",
        "raw": json.dumps(item, ensure_ascii=False),
    }
