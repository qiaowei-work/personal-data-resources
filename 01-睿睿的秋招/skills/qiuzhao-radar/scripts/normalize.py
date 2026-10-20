"""字段归一化与“可投”判定。

原则：
- 不静默丢岗位。字段缺失的进「待核实」，明确不符的进「不推荐」并写原因。
- 专业判定用「平台字段 ∪ JD 正文」，因为平台专业字段经常写少。
- base 地不做硬过滤；异地高匹配单独标注。
"""
from __future__ import annotations

import html
import json
import os
import re
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

DEFAULT_CONFIG = {
    "data_dir": "~/.qiuzhao-radar",
    "grad_year": 2027,
    "target_cities": ["成都", "南京"],
    "majors": [
        "化学工程与技术", "化学工程与工艺", "化学工程", "化学", "应用化学",
        "化工", "应用化工技术", "化工技术", "精细化工技术", "材料与化工",
        "材料科学与工程", "材料化学", "材料物理与化学", "高分子材料",
        "高分子材料与工程", "复合材料与工程", "新能源材料",
        "环境科学与工程", "安全科学与工程", "能源动力", "能源化学工程",
        "资源循环科学与工程", "冶金工程", "不限专业", "专业不限",
    ],
    "keywords": ["化工", "化学", "材料", "工艺", "新能源", "质量", "EHS",
                 "管培生", "2027届", "校园招聘"],
    "topic_keywords": [
        "化工", "化学", "材料", "工艺", "研发", "质量", "EHS", "安全",
        "环保", "环境", "能源", "新能源", "冶金", "分析", "检测", "管培",
        "高分子", "精细化工", "石油", "天然气", "电池", "生物", "制药",
        "生产", "制造", "设备", "电气", "仪表", "自动化", "机械",
    ],
    "strong_topic_keywords": [
        "化工", "化学", "材料", "高分子", "精细化工", "冶金", "电池",
        "新能源", "石油", "天然气", "生物", "制药", "药物", "催化",
        "电化学", "环境工程", "安全工程", "能源化学", "分析化学",
    ],
    "include_internships": False,
    "include_social": False,
    "include_research_institutes": False,
    "scbdc": {
        "enabled": True,
        "days": 30,
        "max_pages": 3,
        "event_days": 60,
        "event_pages": 2,
    },
    "sicau": {"enabled": True, "max_pages": 1, "page_size": 50},
    "ncss": {
        "enabled": True,
        "max_pages": 5,
        "page_size": 20,
        "properties": ["国有企业", "机关/事业单位/非营利机构", "民营企业", "外商投资企业"],
    },
    "iguopin": {"enabled": True, "max_pages": 20, "campus_only": True},
    "ats": {"enabled": True, "max_pages": 3},
    "feishu": {
        "enabled": False,
        "application_base_token": "",
        "application_table_id": "",
        "application_table_name": "投递记录",
        "report_doc_token": "",
        "report_doc_url": "",
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        return deep_merge(DEFAULT_CONFIG, {})
    with open(path, encoding="utf-8") as f:
        user_cfg = json.load(f)
    return deep_merge(DEFAULT_CONFIG, user_cfg)


def clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", str(value))
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"(?<=[一-龥])\s+(?=[一-龥])", "", value)
    return value


def normalize_city(location: Optional[str]) -> str:
    text = clean_text(location)
    if not text:
        return ""
    # “四川省 - 成都市” / “四川省成都市” / “成都”
    cities = re.findall(r"([一-龥]{2,12}市)", text)
    if cities:
        city = cities[0]
        return city[:-1] if city.endswith("市") else city
    for city in ("成都", "南京", "北京", "上海", "广州", "深圳", "杭州", "武汉", "西安", "重庆"):
        if city in text:
            return city
    return text


def infer_grad_year(text: str) -> Optional[int]:
    text = text or ""
    years = [int(x) for x in re.findall(r"(20\d{2})\s*届", text)]
    if years:
        return 2027 if 2027 in years else max(years)
    years = [int(x) for x in re.findall(r"(20\d{2})\s*年[^。；\n]{0,20}?毕业", text)]
    if years:
        return 2027 if 2027 in years else max(years)
    return None


def infer_job_type(title: str, description: str, nature: str = "") -> str:
    title = title or ""
    # 标题优先：宽泛的“2027届校园招聘”公告，正文里提到实习，不应整条判成实习
    if re.search(r"实习|兼职|日常实习|暑期实习|寒假实习|实习转正", title):
        return "实习"
    if re.search(r"社招|社会招聘", title):
        return "社招"
    if re.search(r"校招|校园招聘|应届|2027\s*届|2027\s*年.*毕业", title):
        return "校招"
    text = f"{description} {nature}"
    if re.search(r"实习|兼职|日常实习|暑期实习|寒假实习|实习转正", text):
        return "实习"
    if re.search(r"社招|社会招聘|有工作经验|工作经验\s*[1-9]", text):
        return "社招"
    if re.search(r"校招|校园招聘|应届|2027\s*届|2027\s*年.*毕业", text):
        return "校招"
    if "全职" in nature:
        return "未标注"
    return "未标注"


def infer_education(record: dict, text: str) -> str:
    if record.get("education"):
        return record["education"]
    if "博士" in text and "硕士" not in text:
        return "博士"
    if "硕士" in text or "研究生" in text:
        return "硕士及以上"
    if "本科" in text:
        return "本科及以上"
    if "大专" in text or "专科" in text:
        return "大专"
    return ""


def education_status(education: str) -> Tuple[str, str]:
    """返回 (状态, 说明)。状态：yes / flag / no / unknown。"""
    text = clean_text(education)
    if not text or "不限" in text:
        return "unknown", "学历未注明"
    if "博士" in text and "硕士" not in text:
        return "no", "要求博士"
    if "大专" in text or "专科" in text:
        return "no", "要求大专/专科"
    if "硕士" in text or "研究生" in text:
        return "yes", "硕士可投"
    if "本科" in text:
        # 校招里“本科”经常也收硕士，标 flag 让本人确认，不直接排除
        return "flag", "要求本科（硕士是否可投需确认）"
    return "unknown", "学历口径不明"


def major_status(text: str, majors_cfg: List[str]) -> Tuple[str, str]:
    """字段 ∪ JD 正文命中白名单。"""
    text = clean_text(text)
    if not text:
        return "unknown", "专业未注明"
    if re.search(r"专业不限|不限专业", text):
        return "yes", "不限专业"
    for major in majors_cfg:
        if major and major in text:
            return "yes", f"命中 {major}"
    return "no", "专业未命中"


TARGET_PATTERNS = (
    "化工", "化学", "材料", "工艺", "研发", "技术", "生产", "制造",
    "质量", "品质", "EHS", "安全", "环保", "设备", "电气", "仪表",
    "自动化", "供应链", "管培", "分析", "检测", "化验", "生物", "制药",
)
STRONG_NON_TARGET_PATTERNS = (
    "银行", "农商", "保险", "证券", "基金", "物业", "酒店", "餐饮",
    "零售", "门店", "销售", "客服", "行政", "人力资源", "人事",
    "招聘专员", "招聘主管", "招聘经理", "招聘岗",
    "党群", "党务", "财务", "会计", "法务", "审计", "教师", "讲师", "辅导员",
    "新媒体", "短视频", "直播", "摄影", "剪辑", "翻译", "文秘",
    "前台", "保安", "保洁", "司机",
    "网络安全", "信息安全", "系统管理", "网络工程", "软件工程师", "软件研发",
    "算法工程师", "运维工程师", "数据开发", "数据分析师", "测试开发",
)
WEAK_NON_TARGET_PATTERNS = ("市场", "运营", "电商", "设计")
ANNOUNCEMENT_PATTERNS = (
    "招聘简章", "招聘公告", "招聘启事", "校园招聘公告",
    "秋季校园招聘", "春季校园招聘",
)


def job_family(title: str, description: str) -> str:
    """target / non_target / unknown。

    标题优先；JD 里可能同时列研发/销售，不能因为一个“销售”就整条否决。
    """
    title = title or ""
    description = description or ""
    if any(word in title for word in STRONG_NON_TARGET_PATTERNS):
        return "non_target"
    if any(word in title for word in TARGET_PATTERNS):
        return "target"
    if any(word in description for word in STRONG_NON_TARGET_PATTERNS):
        if not any(word in description for word in TARGET_PATTERNS):
            return "non_target"
    if any(word in description for word in TARGET_PATTERNS):
        return "target"
    if any(word in title for word in WEAK_NON_TARGET_PATTERNS) or \
            any(word in description for word in WEAK_NON_TARGET_PATTERNS):
        return "non_target"
    return "unknown"


def is_announcement(title: str) -> bool:
    """招聘公告/简章不是具体岗位；可以当线索，但不能直接算“可投”。"""
    title = clean_text(title)
    if any(word in title for word in ANNOUNCEMENT_PATTERNS):
        return True
    # “XX 2027届校园招聘”只有公司+批次，没有具体岗位名
    if re.search(r"20\d{2}\s*届.*(校园招聘|校招)$", title):
        return True
    if re.search(r"(校园招聘|校招)$", title) and not re.search(r"[-—:：]", title):
        return True
    return False


def is_operation_job(title: str, category: str, description: str) -> bool:
    text = f"{title} {category}"
    # 只认明确的“操作/普工/技工”岗位名，避免把“工艺工程师”误伤
    if re.search(r"操作工|普工|技工|生产操作员|一线操作|车间操作", text):
        return True
    if re.search(r"化学操作|化工操作员|操作员$", category):
        return True
    return False


def parse_deadline(text: str) -> Optional[str]:
    text = clean_text(text)
    if not text:
        return None
    m = re.search(
        r"(?:截止|报名截止|投递截止)[^0-9]{0,10}(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})",
        text,
    )
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def deadline_passed(deadline: Optional[str]) -> bool:
    if not deadline:
        return False
    try:
        return datetime.strptime(deadline, "%Y-%m-%d").date() < date.today()
    except ValueError:
        return False


def is_topic_relevant(record: dict, cfg: dict) -> bool:
    """用于 NCSS/国聘这种宽口径池子的预过滤，避免把整站岗位都入库。

    标题/专业字段优先；JD 正文只认强主题词，避免“安全管理/质量”这类
    泛词把施工、IT、行政岗位也带进来。
    """
    primary = f"{record.get('title', '')} {record.get('majors', '')}"
    keywords = cfg.get("topic_keywords") or DEFAULT_CONFIG["topic_keywords"]
    if any(word and word in primary for word in keywords):
        return True
    strong = cfg.get("strong_topic_keywords") or DEFAULT_CONFIG["strong_topic_keywords"]
    description = record.get("description", "") or ""
    return any(word and word in description for word in strong)


def prepare_job(record: dict, cfg: dict) -> dict:
    """把 scbdc/sicau 的原始记录转成统一岗位记录。"""
    title = clean_text(record.get("title"))
    description = clean_text(record.get("description"))
    majors = clean_text(record.get("majors"))
    category = clean_text(record.get("job_category"))
    nature = clean_text(record.get("nature"))
    city = normalize_city(record.get("city") or record.get("location"))
    combined = " ".join([title, majors, description])

    grad_year = record.get("grad_year") or infer_grad_year(combined)
    job_type = record.get("job_type") or infer_job_type(title, description, nature)
    education_raw = infer_education(record, combined)
    edu_state, edu_note = education_status(education_raw)
    major_state, major_note = major_status(combined, cfg.get("majors", []))
    operation = is_operation_job(title, category, description)
    family = job_family(title, description)
    announcement = is_announcement(title)
    deadline = record.get("deadline") or parse_deadline(combined)
    target_cities = cfg.get("target_cities", [])
    base_hit = any(c and (c in city or city in c) for c in target_cities) if city else False

    reasons: List[str] = []
    hard_fail = False

    if job_type == "实习" and not cfg.get("include_internships", False):
        reasons.append("实习岗")
        hard_fail = True
    if job_type == "社招" and not cfg.get("include_social", False):
        reasons.append("社招")
        hard_fail = True
    if job_type == "未标注":
        reasons.append("校招/社招未标注")
    if grad_year is not None and grad_year < int(cfg.get("grad_year", 2027)):
        reasons.append(f"{grad_year}届")
        hard_fail = True
    if grad_year is None:
        reasons.append("届别未注明")
    if edu_state == "no":
        reasons.append(edu_note)
        hard_fail = True
    elif edu_state == "flag":
        reasons.append(edu_note)
    elif edu_state == "unknown":
        reasons.append(edu_note)
    if operation:
        reasons.append("一线操作岗")
        hard_fail = True
    if major_state == "no":
        reasons.append(major_note)
    elif major_state == "unknown":
        reasons.append(major_note)
    company_text = clean_text(record.get("company", ""))
    strong_identity = any(
        word in f"{title} {company_text}" for word in STRONG_NON_TARGET_PATTERNS
    )
    if strong_identity:
        reasons.append("非目标岗位（银行/销售/职能等）")
        hard_fail = True
    elif family == "non_target":
        reasons.append("非目标岗位（银行/销售/职能等）")
        # 宽泛公告正文可能同时列了销售/技术岗，不能因为一个词就整条否决；
        # 但标题或公司名本身就是银行/物业/销售等，已在上面明确否决。
        if not announcement:
            hard_fail = True
    elif family == "unknown":
        reasons.append("岗位方向未识别")
    if announcement:
        reasons.append("招聘公告/未列具体岗位")
    if deadline_passed(deadline):
        reasons.append("已过截止日期")
        hard_fail = True
    if not city:
        reasons.append("地点未注明")

    unknown_reasons = ("届别未注明", "学历口径不明", "专业未注明", "专业未命中",
                       "校招/社招未标注", "地点未注明", "岗位方向未识别",
                       "招聘公告/未列具体岗位")
    if hard_fail:
        recommendation = "不推荐"
    elif any(r in reasons for r in unknown_reasons):
        # 先判“待核实”，再判异地；否则一个异地+信息不全的岗位会被误报成异地高匹配
        recommendation = "待核实"
    elif not base_hit and city:
        recommendation = "异地"
    else:
        recommendation = "可投"

    return {
        "company": clean_text(record.get("company", "")),
        "company_type": clean_text(record.get("company_type", "")),
        "sub_company": clean_text(record.get("sub_company", "")),
        "title": title,
        "job_category": category,
        "city": city,
        "location_raw": clean_text(record.get("city") or record.get("location", "")),
        "education": clean_text(education_raw),
        "education_state": edu_state,
        "majors": majors,
        "major_state": major_state,
        "headcount": clean_text(record.get("headcount", "")),
        "salary": clean_text(record.get("salary", "")),
        "description": description,
        "grad_year": grad_year,
        "job_type": job_type,
        "deadline": deadline,
        "publish_date": clean_text(record.get("publish_date", "")),
        "base_hit": base_hit,
        "is_operation": operation,
        "recommendation": recommendation,
        "reasons": reasons,
        "source": record.get("source", ""),
        "source_type": record.get("source_type", ""),
        "source_job_id": str(record.get("source_job_id", "")),
        "url": record.get("url", ""),
        "apply_url": record.get("apply_url", ""),
        "raw": record.get("raw", ""),
    }


def prepare_event(record: dict) -> dict:
    return {
        "source": record.get("source", ""),
        "source_type": record.get("source_type", ""),
        "source_event_id": str(record.get("source_event_id", "")),
        "event_type": record.get("event_type", ""),
        "school": clean_text(record.get("school", "")),
        "title": clean_text(record.get("title", "")),
        "company": clean_text(record.get("company", "")),
        "organizer": clean_text(record.get("organizer", "")),
        "event_date": clean_text(record.get("event_date", "")),
        "deadline": clean_text(record.get("deadline", "")),
        "location": clean_text(record.get("location", "")),
        "url": record.get("url", ""),
        "apply_url": record.get("apply_url", ""),
        "description": clean_text(record.get("description", "")),
        "raw": record.get("raw", ""),
    }
