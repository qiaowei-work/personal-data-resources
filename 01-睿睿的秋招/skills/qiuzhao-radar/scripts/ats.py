"""企业官方 ATS 适配器（北森 / Moka / 飞书招聘）。

ATS = 企业官网背后的招聘系统。不是招聘网站，而是企业自己发布岗位、
接收简历的系统。当前支持三类公开门户：

- 北森：`{slug}.zhiye.com`，公开 `GetJobAdPageList` 接口
- Moka：`app.mokahr.com/campus-recruitment/{orgId}/{siteId}`，响应 AES 加密
- 飞书招聘：`{host}.jobs.feishu.cn`，公开 `/api/v1/search/job/posts`
- hotjob：`{slug}.hotjob.cn`，先标记为待适配（万华/伊利等）

公司到 ATS 的映射在 `data/target_companies.json`。
只读公开岗位，不登录、不投递。
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import subprocess
from typing import List, Optional, Tuple

try:
    from . import net
except ImportError:  # python3 scripts/radar.py
    import net

SOURCE = "ats"
MOKA_IV = "de7c21ed8d6f50fe"


def _clean(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "、".join(_clean(x) for x in value if x)
    if isinstance(value, dict):
        for key in ("name", "cityName", "city_name", "label"):
            if value.get(key):
                return str(value[key])
        return ""
    return str(value).strip()


# ---------------- 北森 ----------------
def fetch_beisen(slug: str, company: str, pages: int = 3, page_size: int = 100) -> List[dict]:
    out: List[dict] = []
    for page in range(pages):
        body = {
            "PortalId": "",
            "PageIndex": page,
            "PageSize": page_size,
            "BusinessType": 2,       # 校招
            "Category": ["2"],
            "KeyWords": "",
            "SpecialType": 0,
        }
        try:
            raw = net.post_json(
                f"https://{slug}.zhiye.com/api/Jobad/GetJobAdPageList",
                body,
                headers={
                    "Origin": f"https://{slug}.zhiye.com",
                    "Referer": f"https://{slug}.zhiye.com/",
                },
            )
            data = json.loads(raw)
        except Exception:
            break
        posts = data.get("Data") or []
        if not posts:
            break
        for job in posts:
            jid = str(job.get("JobAdId") or job.get("Id") or "")
            title = (job.get("JobAdName") or "").strip()
            desc = "\n".join(x for x in [job.get("Duty"), job.get("Require")] if x)
            end = (job.get("EndTime") or "")[:10]
            if end.startswith("0001"):
                end = ""
            out.append({
                "source": SOURCE,
                "source_type": "official_ats",
                "source_job_id": f"beisen:{slug}:{jid}",
                "company": company,
                "title": title,
                "city": _clean(job.get("LocNames") or []),
                "education": "",
                "majors": "",
                "headcount": job.get("HeadCount") or "",
                "salary": _clean(job.get("Salary") or ""),
                "description": desc,
                "job_type": "校招",
                "publish_date": (job.get("PostDate") or "")[:10],
                "deadline": end,
                "url": f"https://{slug}.zhiye.com/campus/jobs",
                "apply_url": f"https://{slug}.zhiye.com/campus/jobs",
                "raw": json.dumps(job, ensure_ascii=False),
            })
        if len(posts) < page_size:
            break
    return out


# ---------------- Moka ----------------
def _moka_decrypt(data_b64: str, key: str) -> str:
    if not data_b64 or not key:
        return ""
    key_b = key.encode("utf-8")
    alg = "aes-256-cbc" if len(key_b) == 32 else "aes-128-cbc"
    key_hex = binascii.hexlify(key_b).decode()
    iv_hex = binascii.hexlify(MOKA_IV.encode()).decode()
    cipher = base64.b64decode(data_b64)
    p = subprocess.run(
        ["openssl", "enc", "-d", "-" + alg, "-K", key_hex, "-iv", iv_hex],
        input=cipher, capture_output=True,
    )
    if p.returncode != 0:
        return ""
    return p.stdout.decode("utf-8", "replace")


def fetch_moka(org_id: str, site_id: str, company: str,
               pages: int = 3, page_size: int = 30) -> List[dict]:
    out: List[dict] = []
    for page in range(pages):
        body = {
            "orgId": org_id, "siteId": site_id, "limit": page_size,
            "offset": page * page_size, "needStat": True,
            "jobIdTopList": [], "departmentIds": [], "customFields": {},
            "site": "campus", "locale": "zh-CN",
        }
        try:
            raw = net.post_json(
                "https://app.mokahr.com/api/outer/ats-apply/website/jobs/v2",
                body,
                headers={
                    "Origin": "https://app.mokahr.com",
                    "Referer": f"https://app.mokahr.com/campus-recruitment/{org_id}/{site_id}",
                },
            )
            envelope = json.loads(raw)
            text = _moka_decrypt(envelope.get("data", ""), envelope.get("necromancer", ""))
            data = json.loads(text)
        except Exception:
            break
        jobs = (((data.get("data") or {}).get("jobs")) or [])
        if not jobs:
            break
        for job in jobs:
            jid = str(job.get("id") or "")
            title = (job.get("title") or "").strip()
            locations = job.get("locations") or job.get("location") or []
            city = _clean(locations)
            project = (job.get("projectFolder") or {}).get("name", "")
            desc = "\n".join(x for x in [
                project, job.get("jobDescription") or job.get("description") or ""
            ] if x)
            grad = None
            m_year = re.search(r"(20\d{2})\s*届", project)
            if m_year:
                grad = int(m_year.group(1))
            out.append({
                "source": SOURCE,
                "source_type": "official_ats",
                "source_job_id": f"moka:{org_id}:{site_id}:{jid}",
                "company": company,
                "title": title,
                "city": city,
                "education": "",
                "majors": "",
                "headcount": job.get("headcount") or "",
                "salary": "",
                "description": desc,
                "grad_year": grad,
                "job_type": "校招",
                "publish_date": (job.get("publishedAt") or job.get("openedAt") or "")[:10],
                "deadline": "",
                "url": f"https://app.mokahr.com/campus-recruitment/{org_id}/{site_id}",
                "apply_url": f"https://app.mokahr.com/campus-recruitment/{org_id}/{site_id}",
                "raw": json.dumps(job, ensure_ascii=False),
            })
        if len(jobs) < page_size:
            break
    return out


# ---------------- 飞书招聘 ----------------
def fetch_feishu(host: str, company: str, pages: int = 3, page_size: int = 50) -> List[dict]:
    try:
        homepage = net.get(f"https://{host}/")
    except Exception:
        return []
    path = ""
    m = re.search(r'id="js-websiteInfo"[^>]*>(.*?)</script>', homepage, re.S)
    if m:
        try:
            path = ((json.loads(m.group(1)).get("website_info")) or {}).get("path", "") or ""
        except Exception:
            path = ""
    out: List[dict] = []
    for page in range(pages):
        body = {
            "keyword": "", "limit": page_size, "offset": page * page_size,
            "portal_type": 2, "job_category_id_list": [],
            "location_code_list": [], "subject_id_list": [],
            "recruitment_id_list": [], "job_function_id_list": [],
        }
        try:
            raw = net.post_json(
                f"https://{host}/api/v1/search/job/posts",
                body,
                headers={
                    "Origin": f"https://{host}", "Referer": f"https://{host}/",
                    "Portal-Channel": "office", "Portal-Platform": "pc",
                    "website-path": path,
                },
            )
            data = json.loads(raw)
        except Exception:
            break
        items = (((data.get("data") or {}).get("job_post_list")) or [])
        if not items:
            break
        for job in items:
            recruit = job.get("recruit_type") or {}
            parent = (recruit.get("parent") or {}).get("name", "") if isinstance(recruit, dict) else ""
            if parent and ("社招" in parent):
                continue
            desc = "\n".join(x for x in [job.get("description"), job.get("requirement")] if x)
            city = _clean(job.get("city_info") or [])
            out.append({
                "source": SOURCE,
                "source_type": "official_ats",
                "source_job_id": f"feishu:{host}:{job.get('id')}",
                "company": company,
                "title": (job.get("title") or "").strip(),
                "city": city,
                "education": "",
                "majors": "",
                "headcount": "",
                "salary": "",
                "description": desc,
                "job_type": "校招" if "校" in parent else "",
                "publish_date": "",
                "deadline": "",
                "url": f"https://{host}/",
                "apply_url": f"https://{host}/",
                "raw": json.dumps(job, ensure_ascii=False),
            })
        if len(items) < page_size:
            break
    return out


# ---------------- 公司映射 ----------------
def discover(url: str) -> Tuple[str, str]:
    """从招聘门户 URL 识别 ATS 类型和 ref。"""
    url = (url or "").strip()
    m = re.search(r"mokahr\.com/(?:m/)?campus-recruitment/([^/]+)/(\d+)", url)
    if m:
        return "moka", f"{m.group(1)}/{m.group(2)}"
    m = re.search(r"([A-Za-z0-9-]+)\.zhiye\.com", url)
    if m:
        return "beisen", m.group(1)
    m = re.search(r"https?://([^/]+\.jobs\.feishu\.cn)", url)
    if m:
        return "feishu", m.group(1)
    m = re.search(r"([A-Za-z0-9-]+)\.hotjob\.cn", url)
    if m:
        return "hotjob", m.group(1)
    return "unknown", ""


def fetch_company(entry: dict, pages: int = 3) -> List[dict]:
    typ = (entry.get("ats_type") or "").lower()
    ref = entry.get("ats_ref") or ""
    company = entry.get("name") or ""
    try:
        if typ == "beisen" and ref:
            return fetch_beisen(ref, company, pages=pages)
        if typ == "moka" and "/" in ref:
            org_id, site_id = ref.split("/", 1)
            return fetch_moka(org_id, site_id, company, pages=pages)
        if typ == "feishu" and ref:
            return fetch_feishu(ref, company, pages=pages)
    except Exception:
        return []
    return []


def load_companies(path: str) -> List[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
