"""脚本级去重。

三层键：
1. 来源级：source + source_job_id（同一来源重复跑）
2. 公司级：company_id（公司别名/全称/简称归并；只用于公司库和分组）
3. 岗位级：company_id + sub_company + title + city + grad_year
   （同一岗位出现在川e就/川农/其他学校时合并）

注意：公司名只做“公司级”去重，不能单独作为岗位去重键。
否则中铝一家公司的几百个岗位会被合成一条。
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import unicodedata
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SOURCE_PRIORITY = {
    "official_ats": 5,
    "scbdc": 4,
    "sicau": 4,
    "school_official": 4,
    "aggregator": 2,
    "manual": 1,
}

LEGAL_SUFFIXES = [
    "股份有限公司", "有限责任公司", "集团有限公司", "有限公司",
    "集团", "公司",
]


def _clean(value: Optional[str]) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", str(value))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"(?<=[一-龥])\s+(?=[一-龥])", "", value)
    return value


def normalize_company_name(name: Optional[str]) -> str:
    text = _clean(name)
    text = re.sub(r"[（）()\[\]【】、,，.。·:：]", "", text)
    text = re.sub(r"\s+", "", text)
    changed = True
    while changed:
        changed = False
        for suffix in LEGAL_SUFFIXES:
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)]
                changed = True
                break
    return text


class CompanyResolver:
    def __init__(self, alias_path: Optional[str] = None):
        self.aliases: Dict[str, str] = {}
        if alias_path and os.path.exists(alias_path):
            with open(alias_path, encoding="utf-8") as f:
                raw = json.load(f)
            for alias, canonical in raw.items():
                self.aliases[normalize_company_name(alias)] = canonical

    def resolve(self, name: Optional[str]) -> Tuple[str, str]:
        """返回 (company_id, canonical_name)。"""
        canonical = normalize_company_name(name)
        canonical = self.aliases.get(canonical, canonical)
        company_id = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]
        return company_id, canonical


def normalize_title(title: Optional[str]) -> str:
    text = _clean(title)
    # 去掉开头的【...】/（...）标签
    text = re.sub(r"^[【\[（(].*?[】\]）)]\s*", "", text)
    # 去掉只含届别/批次/地点的括号
    text = re.sub(
        r"[（(](?:20\d{2}\s*届?|校招|秋招|春招|急聘|补录|base|地点|城市|"
        r"成都|南京|北京|上海|广州|深圳|杭州|武汉|西安|重庆|宁波|苏州|青岛|郑州)"
        r"[^）)]*[）)]",
        "",
        text,
    )
    text = re.sub(
        r"(20\d{2}\s*届|校园招聘|秋季招聘|春季招聘|校招|秋招|春招|补录|急聘)",
        "",
        text,
    )
    text = re.sub(r"[\s\-—_·:：,，、/|]+", "", text)
    return text.lower()


def canonical_url(url: Optional[str]) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    drop = {"from", "source", "timestamp", "share", "spm", "scene", "utm_source",
            "utm_medium", "utm_campaign", "utm_term", "utm_content"}
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in drop]
    query.sort()
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def title_similarity(a: Optional[str], b: Optional[str]) -> float:
    a_norm = normalize_title(a)
    b_norm = normalize_title(b)
    if not a_norm or not b_norm:
        return 0.0
    return difflib.SequenceMatcher(None, a_norm, b_norm).ratio()


def _ngrams(text: str, n: int = 3) -> set:
    text = re.sub(r"\s+", "", _clean(text))
    return {text[i:i + n] for i in range(max(0, len(text) - n + 1))}


def jd_similarity(a: Optional[str], b: Optional[str]) -> float:
    a_set = _ngrams(a or "")
    b_set = _ngrams(b or "")
    if not a_set or not b_set:
        return 0.0
    return len(a_set & b_set) / len(a_set | b_set)


def job_key(job: dict, resolver: CompanyResolver) -> str:
    company_id, _ = resolver.resolve(_company_name(job))
    sub = normalize_company_name(job.get("sub_company", ""))
    city = _clean(job.get("city", ""))
    year = str(job.get("grad_year") or "")
    title = normalize_title(job.get("title", ""))
    return "|".join([company_id, sub, title, city, year])


def _company_name(job: dict) -> str:
    # DB 行只有 company_name，新抓记录只有 company
    return job.get("company") or job.get("company_name") or ""


def block_key(job: dict, resolver: CompanyResolver) -> Tuple[str, str]:
    company_id, _ = resolver.resolve(_company_name(job))
    return company_id, _clean(job.get("city", ""))


def duplicate_reason(a: dict, b: dict, resolver: CompanyResolver) -> Optional[str]:
    """判断两条岗位是否同一个岗位；返回原因或 None。"""
    a_id, _ = resolver.resolve(_company_name(a))
    b_id, _ = resolver.resolve(_company_name(b))
    if not a_id or a_id != b_id:
        return None

    a_city = _clean(a.get("city", ""))
    b_city = _clean(b.get("city", ""))
    if a_city and b_city and a_city != b_city:
        return None

    a_year = a.get("grad_year")
    b_year = b.get("grad_year")
    if a_year and b_year and a_year != b_year:
        return None

    t_sim = title_similarity(a.get("title"), b.get("title"))
    if t_sim >= 0.96:
        return f"标题高度相似 {t_sim:.2f}"
    if t_sim >= 0.90:
        j_sim = jd_similarity(a.get("description"), b.get("description"))
        if j_sim >= 0.65:
            return f"标题 {t_sim:.2f} + JD {j_sim:.2f}"
        if not (a.get("description") or b.get("description")):
            return f"标题 {t_sim:.2f}（JD 缺失）"
    return None


def pick_better(a: dict, b: dict, field: str) -> object:
    """按来源优先级和字段完整性选值。"""
    pa = SOURCE_PRIORITY.get(a.get("source", ""), 0)
    pb = SOURCE_PRIORITY.get(b.get("source", ""), 0)
    va, vb = a.get(field), b.get(field)
    if not va:
        return vb
    if not vb:
        return va
    if pb > pa:
        return vb
    if pb == pa and len(str(vb)) > len(str(va)):
        return vb
    return va
