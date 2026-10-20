"""川e就—四川大学生就业服务平台适配器。

覆盖：
  /job/search   平台职位（列表自带 JD 摘要）
  /campus       学校招聘公告
  /teachin      学校宣讲会
  /jobfair      学校招聘会/双选会

页面列表是 base64 + zlib 压缩后内嵌在 HTML 里的，解码顺序：
  unzip(payload) -> substr(a) -> Base64.decode(...) -> substr(b)
"""
from __future__ import annotations

import base64
import html
import json
import re
import time
import zlib
from typing import Dict, Iterable, List, Optional
from urllib.parse import quote, urljoin

try:
    from . import net
except ImportError:  # python3 scripts/radar.py
    import net

BASE = "https://bigdata.scbdc.edu.cn:8888"
SOURCE = "scbdc"
PLATFORM_NAME = "川e就—四川大学生就业服务平台"


def clean(value: Optional[str]) -> str:
    if not value:
        return ""
    value = html.unescape(re.sub(r"<[^>]+>", " ", value))
    value = re.sub(r"\s+", " ", value).strip()
    # 站点会在关键词命中处插 <strong>，导致“化工 工艺”这类空格；
    # 中文之间的空格不是语义空格，合并掉。
    value = re.sub(r"(?<=[一-龥])\s+(?=[一-龥])", "", value)
    return value


def _first(pattern: str, text: str, default: str = "") -> str:
    m = re.search(pattern, text, re.S)
    return m.group(1) if m else default


def decode_page(page: str) -> str:
    """解出列表页内嵌的压缩 HTML；没有 payload 时返回空串。"""
    m = re.search(
        r'Base64\.decode\(unzip\("([^"]+)"\)(?:\.substr\((\d+)\))?\)(?:\.substr\((\d+)\))?',
        page,
    )
    if not m:
        return ""
    payload, a, b = m.group(1), m.group(2), m.group(3)
    try:
        raw = zlib.decompress(base64.b64decode(payload), 15).decode("utf-8", "replace")
        if a:
            raw = raw[int(a):]
        decoded = base64.b64decode(raw).decode("utf-8", "replace")
        if b:
            decoded = decoded[int(b):]
        return decoded
    except Exception:
        return ""


def _dl_pairs(block: str) -> Dict[str, str]:
    """解析 <dl class=dl-horizontal><dt>..</dt><dd>..</dd></dl>。

    有些站点的 <dd> 是空的，真正的专业列表紧跟在 </dd> 之后，
    所以这里把 dd 后面到 </dl> 之间的文本一并保留。
    """
    out: Dict[str, str] = {}
    for dl in re.findall(r'<dl class="dl-horizontal">(.*?)</dl>', block, re.S):
        key = clean(_first(r"<dt>(.*?)</dt>", dl)).rstrip("：:")
        if not key:
            continue
        m = re.search(r"<dd>(.*?)</dd>(.*)", dl, re.S)
        val = clean((m.group(1) + " " + m.group(2)) if m else dl)
        if key == "工作性质" and key in out:
            continue
        out[key] = val
    return out


def parse_job_cards(page: str) -> List[dict]:
    jobs: List[dict] = []
    for block in re.split(r'(?=<li data-id="\d+">)', page):
        if not block.startswith('<li data-id="'):
            continue
        job_id = _first(r'data-id="(\d+)"', block)
        if not job_id:
            continue
        company = clean(_first(r'<div class="company">\s*<a[^>]*>(.*?)</a>', block))
        company_type = clean(
            _first(r'<div class="company">.*?<div class="clearfix">\s*<ul>\s*<li>(.*?)</li>', block)
        )
        title_m = re.search(
            r'<div class="name[^"]*">\s*<a href="([^"]+)"[^>]*>(.*?)</a>', block, re.S
        )
        title = clean(title_m.group(2)) if title_m else ""
        url = urljoin(BASE, title_m.group(1)) if title_m else ""
        salary = clean(_first(r'<span class="text-orange">(.*?)</span>', block))
        salary = re.sub(r"^月薪[:：]\s*", "", salary)
        publish_date = clean(
            _first(r'<p class="text-center time-muted">\s*(.*?)\s*</p>', block)
        )
        dls = _dl_pairs(block)
        jd = clean(_first(r'<div class="job-res">(.*?)</div>', block))
        if not jd:
            # 兜底：去掉标签后取详情字段之后的内容，避免整张卡片都丢掉
            tail = block.split("</dl>")[-1]
            tail = re.sub(r'<div class="job-tag">.*?</div>', " ", tail, flags=re.S)
            jd = clean(tail)[:2000]
        jobs.append({
            "source": SOURCE,
            "source_type": "official_platform",
            "source_job_id": job_id,
            "company": company,
            "company_type": company_type,
            "title": title,
            "url": url,
            "apply_url": url,
            "salary": salary,
            "publish_date": publish_date,
            "city": dls.get("工作地点", ""),
            "nature": dls.get("工作性质", ""),
            "job_category": dls.get("职位类别", ""),
            "education": dls.get("学历要求", ""),
            "majors": dls.get("需求专业", ""),
            "language": dls.get("语言要求", ""),
            "headcount": dls.get("招聘人数", ""),
            "description": jd,
            "raw": json.dumps(dls, ensure_ascii=False),
        })
    return jobs


def max_page(decoded: str) -> int:
    text = clean(decoded)
    m = re.search(r"\.\.\.\s*(\d+)\s*下一页", text)
    if m:
        return int(m.group(1))
    nums = [int(x) for x in re.findall(r"page=(\d+)", decoded)]
    return max(nums) if nums else 1


def fetch_jobs(keyword: str, max_pages: int = 2, days: int = 30,
               delay: float = 0.6) -> List[dict]:
    """按关键词抓取平台职位。只读公开列表，不申请职位。"""
    jobs: List[dict] = []
    limiter = net.RateLimiter(delay)
    for page in range(1, max_pages + 1):
        url = (
            f"{BASE}/job/search?keyword={quote(keyword)}"
            f"&page={page}&time={days}&source=0"
        )
        limiter.wait()
        try:
            page_html = net.get(url, insecure=True)
        except net.HttpError:
            break
        decoded = decode_page(page_html)
        if not decoded:
            break
        batch = parse_job_cards(decoded)
        if not batch:
            break
        jobs.extend(batch)
        if page >= max_page(decoded):
            break
    return _dedupe_by_id(jobs)


def _event_id(url: str) -> str:
    m = re.search(r"/view/id/(\d+)", url or "")
    return m.group(1) if m else url


def parse_campus(decoded: str, school: str) -> List[dict]:
    events: List[dict] = []
    list_part = _first(r'<div class="list">(.*?)</div>\s*</div>\s*</div>', decoded)
    if not list_part:
        list_part = decoded
    for block in re.findall(r"<ul>(.*?)</ul>", list_part, re.S):
        m = re.search(r'<a href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        url = urljoin(BASE, m.group(1))
        title = clean(m.group(2))
        school_name = clean(_first(r'<li class="percent30">.*?<span>(.*?)</span>', block, school))
        date = clean(_first(r'<li class="percent15">.*?<span>(.*?)</span>', block))
        events.append({
            "source": SOURCE,
            "source_type": "official_platform",
            "source_event_id": _event_id(url),
            "event_type": "campus",
            "school": school_name or school,
            "title": title,
            "company": "",
            "organizer": school_name or school,
            "event_date": date,
            "location": "",
            "url": url,
        })
    return events


def parse_jobfair(decoded: str, school: str) -> List[dict]:
    events: List[dict] = []
    list_part = _first(r'<div class="list">(.*?)</div>\s*</div>\s*</div>', decoded)
    if not list_part:
        list_part = decoded
    for block in re.findall(r"<ul>(.*?)</ul>", list_part, re.S):
        m = re.search(r'<a href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        url = urljoin(BASE, m.group(1))
        title = clean(m.group(2))
        organizer = clean(_first(r'<li class="w-200">.*?<span>(.*?)</span>', block, school))
        location = clean(_first(r'<li class="w-250">.*?<span>(.*?)</span>', block))
        time_text = clean(_first(r'<li class="w-280[^"]*">.*?<span>(.*?)</span>', block))
        date_m = re.search(r"(\d{4}-\d{2}-\d{2})", time_text)
        status = clean(_first(r'<span class="fair-status">(.*?)</span>', block))
        events.append({
            "source": SOURCE,
            "source_type": "official_platform",
            "source_event_id": _event_id(url),
            "event_type": "jobfair",
            "school": organizer or school,
            "title": title,
            "company": "",
            "organizer": organizer or school,
            "event_date": date_m.group(1) if date_m else "",
            "time_text": time_text,
            "location": location,
            "status": status,
            "url": url,
        })
    return events


def parse_teachin(decoded: str, school: str) -> List[dict]:
    """宣讲会表格结构在不同学校略有差异，这里用宽松解析。"""
    events: List[dict] = []
    list_part = _first(r'<div class="list">(.*?)</div>\s*</div>\s*</div>', decoded)
    if not list_part:
        list_part = decoded
    for block in re.findall(r"<ul>(.*?)</ul>", list_part, re.S):
        m = re.search(r'<a href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        url = urljoin(BASE, m.group(1))
        title = clean(m.group(2))
        cells = [clean(x) for x in re.findall(r"<li[^>]*>(.*?)</li>", block, re.S)]
        cells = [x for x in cells if x]
        time_text = next((x for x in cells if re.search(r"\d{4}-\d{2}-\d{2}", x)), "")
        date_m = re.search(r"(\d{4}-\d{2}-\d{2})", time_text)
        location = next(
            (x for x in cells if re.search(r"校区|楼|厅|室|中心|广场|礼堂", x)), ""
        )
        organizer = next((x for x in cells if x == school), school)
        events.append({
            "source": SOURCE,
            "source_type": "official_platform",
            "source_event_id": _event_id(url),
            "event_type": "teachin",
            "school": organizer or school,
            "title": title,
            "company": title,
            "organizer": organizer or school,
            "event_date": date_m.group(1) if date_m else "",
            "time_text": time_text,
            "location": location,
            "url": url,
        })
    return events


def fetch_school_events(school_id: str, school: str,
                        event_types: Iterable[str] = ("campus", "jobfair", "teachin"),
                        max_pages: int = 2, days: int = 60,
                        delay: float = 0.6) -> List[dict]:
    """抓一所学校在川e就上的公告/招聘会/宣讲会。"""
    events: List[dict] = []
    limiter = net.RateLimiter(delay)
    parsers = {
        "campus": (f"{BASE}/campus", parse_campus),
        "jobfair": (f"{BASE}/jobfair", parse_jobfair),
        "teachin": (f"{BASE}/teachin", parse_teachin),
    }
    for event_type in event_types:
        if event_type not in parsers:
            continue
        endpoint, parser = parsers[event_type]
        for page in range(1, max_pages + 1):
            url = f"{endpoint}?universityid={quote(str(school_id))}&time={days}&page={page}"
            limiter.wait()
            try:
                page_html = net.get(url, insecure=True)
            except net.HttpError:
                break
            decoded = decode_page(page_html)
            if not decoded:
                break
            batch = parser(decoded, school)
            if not batch:
                break
            events.extend(batch)
            if page >= max_page(decoded):
                break
    return _dedupe_events(events)


def fetch_school_options() -> List[dict]:
    """从川e就 /campus 页的学校下拉框读取 224 个学校/院所。"""
    page = net.get(f"{BASE}/campus", insecure=True)
    m = re.search(r'<select[^>]*name="universityid"[^>]*>(.*?)</select>', page, re.S)
    if not m:
        return []
    options = []
    for value, label in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', m.group(1), re.S):
        name = clean(label)
        if value and name:
            options.append({"id": value, "name": name})
    return options


def _dedupe_by_id(jobs: List[dict]) -> List[dict]:
    seen = set()
    out = []
    for job in jobs:
        key = job.get("source_job_id")
        if key and key in seen:
            continue
        seen.add(key)
        out.append(job)
    return out


def _dedupe_events(events: List[dict]) -> List[dict]:
    seen = set()
    out = []
    for event in events:
        key = (event.get("event_type"), event.get("source_event_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(event)
    return out
