"""飞书写入与投递记录读取。

输出目标（用户现有飞书）：
  每个公司 -> 简历投递记录 / 投递记录（一行一个公司）
  日报 -> 本地 Markdown（飞书不单独建日报）

- 一行一个公司；岗位只作为备注里的线索，不写「岗位名称」。
- 公司级去重：本地 feishu_company_synced + 表内已有「公司」名；已有公司不重复建行。
- 公司下所有岗位都“不推荐”时不写入；有可投/待核实/异地任一才写。
- 当前投递记录表没有「二级单位 / 下一步」列，这两项写进「备注」。
- 城市字段已改为多选，按 南京 / 成都 / 其他 写入。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import Counter
from typing import Dict, List, Tuple

try:
    from .store import Store
except ImportError:  # python3 scripts/radar.py
    from store import Store

# 飞书字段 ← 内部字段
JOB_FIELD_MAP = {
    "岗位名称": "title",
    "岗位标识": "job_key",
    "公司": "company_name",
    "二级单位": "sub_company",
    "岗位类别": "job_category",
    "城市": "city",
    "学历": "education",
    "专业要求": "majors",
    "届别": "grad_year",
    "招聘人数": "headcount",
    "截止日期": "deadline",
    "判定": "recommendation",
    "原因/备注": "reasons",
    "来源": "source",
    "核验状态": "verification_status",
    "官方链接": "url",
    "首次发现": "first_seen",
    "最近看到": "last_seen",
    "状态": "status",
    "来源明细": "sources",
}
SELECT_FIELDS = {"判定", "核验状态", "状态"}
DATETIME_FIELDS = {"截止日期", "首次发现", "最近看到"}


def _lark(args: List[str], timeout: int = 60) -> dict:
    exe = shutil.which("lark-cli")
    if not exe:
        raise RuntimeError("找不到 lark-cli")
    p = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"lark-cli 失败：{p.stderr.strip()[:400]}")
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"lark-cli 返回不是 JSON：{p.stdout[:300]}") from exc


def _table_rows(base_token: str, table_id: str, as_user: bool = True) -> Tuple[List[str], List[dict]]:
    """读整张表；返回 (字段名列表, 记录字典列表)。"""
    fields: List[str] = []
    rows: List[dict] = []
    offset = 0
    while True:
        args = [
            "base", "+record-list",
            "--base-token", base_token,
            "--table-id", table_id,
            "--limit", "200",
            "--offset", str(offset),
            "--format", "json",
        ]
        if as_user:
            args += ["--as", "user"]
        data = _lark(args)
        payload = data.get("data") or {}
        if not fields:
            fields = payload.get("fields") or []
        record_ids = payload.get("record_id_list") or []
        page_rows = payload.get("data") or []
        for idx, row in enumerate(page_rows):
            item = dict(zip(fields, row))
            item["_record_id"] = record_ids[idx] if idx < len(record_ids) else ""
            rows.append(item)
        if not payload.get("has_more") or not page_rows:
            break
        offset += len(page_rows)
    return fields, rows


def _record_id_map(base_token: str, table_id: str, key_field: str) -> Dict[str, str]:
    """读岗位池，建立 岗位标识 -> record_id 映射。"""
    try:
        _, rows = _table_rows(base_token, table_id)
    except Exception:
        return {}
    out = {}
    for row in rows:
        key = str(row.get(key_field) or "").strip()
        rec_id = str(row.get("_record_id") or "").strip()
        if key and rec_id:
            out[key] = rec_id
    return out


# ---------------- 投递记录表（公司级） ----------------
APPLICATION_FIELD_MAP = {
    "公司": "company_name",
    "公司类型": "company_type",
    "城市": "city",
    "备注": "remark",
    "投递状态": "apply_status",
    "岗位链接": "url",
    "截止日期": "deadline",
    "优先级": "priority",
}

COMPANY_TYPE_OPTIONS = {"央国企", "民企", "外企", "研究所", "公务员", "事业编", "其他"}
CITY_OPTIONS = {"南京", "成都", "其他"}
PRIORITY_OPTIONS = {"首选", "次选", "备选", "降级"}
APPLY_STATUS_OPTIONS = {"待投", "已投", "笔试", "面试", "Offer", "已拒", "已放弃"}

CENTRAL_SOE = (
    "中铝", "中国石化", "中石化", "中国石油", "中石油", "中国中化", "中化",
    "国家能源", "中国五矿", "中国建材", "中国化学工程", "华润", "中核", "中广核",
    "中国中车", "中国节能", "国投", "中国航天", "中粮", "中国通服", "中国广核",
    "四川发展", "成都产投", "金陵石化", "扬子石化", "南化", "中铁", "中建",
)
FOREIGN = (
    "巴斯夫", "陶氏", "赢创", "科思创", "林德", "液化空气", "联合利华", "宝洁",
    "壳牌", "拜耳", "默克", "赛诺菲", "阿斯利康", "霍尼韦尔", "3M", "杜邦",
    "施耐德", "西门子", "ABB", "罗氏", "诺华", "辉瑞", "强生", "特斯拉",
)
RESEARCH = ("研究院", "研究所", "中科院", "实验室", "研究设计院")
PRIVATE_KNOWN = ("宁德时代", "比亚迪", "药明康德", "凯莱英", "博腾", "九洲药业", "科伦", "倍特")


def _first_value(value):
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


def _map_company_type(job: dict) -> str:
    raw = str(job.get("company_type") or "")
    company = str(job.get("company_name") or "")
    text = raw + company
    if any(word in text for word in ("国有企业", "国企", "中央企业", "央企")) or \
            any(word in company for word in CENTRAL_SOE):
        return "央国企"
    if any(word in text for word in ("外商投资", "外资", "外企")) or \
            any(word in company for word in FOREIGN):
        return "外企"
    if any(word in text for word in ("科研设计单位",)) or \
            any(word in company for word in RESEARCH):
        return "研究所"
    if "机关" in text:
        return "公务员"
    if "事业" in text:
        return "事业编"
    if any(word in text for word in ("民营", "私企", "其他企业")):
        return "民企"
    if any(word in company for word in PRIVATE_KNOWN):
        return "民企"
    return "其他"


def _city_values(job: dict) -> List[str]:
    text = f"{job.get('city') or ''} {job.get('location_raw') or ''}"
    values = []
    if "成都" in text:
        values.append("成都")
    if "南京" in text:
        values.append("南京")
    if not values:
        values.append("其他")
    return values


def _priority(job: dict) -> str:
    rec = job.get("recommendation")
    if rec == "可投":
        return "首选"
    if rec == "待核实":
        return "备选"
    if rec == "异地":
        return "降级"
    return "备选"


def _next_step(job: dict) -> str:
    rec = job.get("recommendation")
    if rec == "可投":
        return "准备投递"
    if rec == "异地":
        return "评估异地"
    return "核实届别/专业/截止"


def _application_payload(job: dict) -> dict:
    reasons = "；".join(job.get("reasons", [])) if isinstance(job.get("reasons"), list) else str(job.get("reasons") or "")
    remark = (
        f"判定：{job.get('recommendation') or ''}；原因：{reasons or '无'}；"
        f"学历：{job.get('education') or '未注明'}；专业：{job.get('majors') or '未注明'}；"
        f"届别：{job.get('grad_year') or '未注明'}；招聘人数：{job.get('headcount') or '未注明'}；"
        f"二级单位：{job.get('sub_company') or '未注明'}；岗位ID：{job.get('source_job_id') or '未注明'}；"
        f"建议下一步：{_next_step(job)}；"
        f"来源：{job.get('source') or ''}；核验：{job.get('verification_status') or ''}；"
        f"截止：{job.get('deadline') or '未注明'}"
    )[:1000]
    return {
        "公司": job.get("company_name") or "",
        "公司类型": [_map_company_type(job)],
        "城市": _city_values(job),
        "备注": remark,
        "投递状态": ["待投"],
        "岗位链接": job.get("url") or "",
        "截止日期": (job.get("deadline") or "")[:10],
        "优先级": [_priority(job)],
    }


def _application_key(row: dict) -> str:
    company = str(row.get("公司") or "").strip()
    title = str(row.get("岗位名称") or "").strip()
    return f"{company}|{title}"


def _company_payload(jobs: List[dict]) -> dict:
    """一个公司一条记录：岗位只作为备注里的线索，不写岗位名称。"""
    actionable = [j for j in jobs if j.get("recommendation") != "不推荐"]
    if not actionable:
        return {}
    first = actionable[0]
    company = str(first.get("company_name") or "").strip()
    if not company:
        return {}
    rec_counts = Counter(str(j.get("recommendation") or "") for j in jobs)
    city_set = set()
    for j in jobs:
        city_set.update(_city_values(j))
    cities = [c for c in ("成都", "南京", "其他") if c in city_set] or ["其他"]

    if rec_counts.get("可投"):
        priority = "首选"
    elif rec_counts.get("待核实"):
        priority = "备选"
    else:
        priority = "降级"

    deadlines = [str(j.get("deadline"))[:10] for j in actionable if j.get("deadline")]
    deadline = min(deadlines) if deadlines else ""

    urls = Counter(str(j.get("url") or "") for j in actionable if j.get("url"))
    url = urls.most_common(1)[0][0] if urls else ""

    reasons = Counter()
    for j in actionable:
        for r in (j.get("reasons") or []):
            reasons[str(r)] += 1
    reason_text = "、".join(f"{r}×{n}" if n > 1 else r for r, n in reasons.most_common(4))

    ids = []
    for j in actionable:
        sid = str(j.get("source_job_id") or "").strip()
        if sid and sid not in ids:
            ids.append(sid)
    id_text = "、".join(ids[:12]) + (f" 等 {len(ids)} 个" if len(ids) > 12 else "")

    sources = "、".join(sorted({str(j.get("source") or "") for j in actionable if j.get("source")}))
    verifications = "、".join(sorted({str(j.get("verification_status") or "") for j in actionable if j.get("verification_status")}))
    remark = (
        f"雷达发现 {len(jobs)} 个岗位：可投 {rec_counts.get('可投', 0)} / "
        f"待核实 {rec_counts.get('待核实', 0)} / 异地 {rec_counts.get('异地', 0)} / "
        f"不推荐 {rec_counts.get('不推荐', 0)}。"
        f"城市：{'、'.join(cities)}；来源：{sources or '未注明'}；核验：{verifications or '未注明'}；"
        f"岗位ID：{id_text or '未注明'}；主要判定：{reason_text or '无'}；"
        f"截止：{deadline or '未注明'}"
    )[:1000]

    return {
        "公司": company,
        "公司类型": [_map_company_type(first)],
        "城市": cities,
        "备注": remark,
        "投递状态": ["待投"],
        "岗位链接": url,
        "截止日期": deadline,
        "优先级": [priority],
    }


def _existing_application_keys(base_token: str, table_id: str) -> set:
    try:
        _, rows = _table_rows(base_token, table_id)
    except Exception:
        return set()
    return {_application_key(row) for row in rows if _application_key(row)}


def _job_payload(job: dict) -> dict:
    payload = {}
    for field, key in JOB_FIELD_MAP.items():
        value = job.get(key)
        if key == "reasons":
            value = "；".join(job.get("reasons", []))
        elif key == "sources":
            sources = job.get("sources", [])
            value = "；".join(
                f"{s.get('source')}: {s.get('url', '')}" for s in sources if s.get("url")
            )
        elif key == "job_key":
            value = job.get("job_key") or f"{job.get('source')}:{job.get('source_job_id')}"
        if value in (None, "", []):
            continue
        if field in SELECT_FIELDS:
            payload[field] = [str(value)]
        elif field in DATETIME_FIELDS:
            payload[field] = str(value)[:10]
        elif field == "届别":
            try:
                payload[field] = int(value)
            except (TypeError, ValueError):
                continue
        else:
            payload[field] = str(value)
    return payload


def _create_records(base_token: str, table_id: str, records: List[dict], dry_run: bool) -> int:
    if not records:
        return 0
    clean_records = [
        {k: v for k, v in record.items() if v not in (None, "", [])}
        for record in records
    ]
    payload = {"create_records": clean_records}
    if dry_run:
        print(json.dumps(payload, ensure_ascii=False)[:4000])
        return len(records)
    args = [
        "base", "+record-batch-create",
        "--base-token", base_token,
        "--table-id", table_id,
        "--json", json.dumps(payload, ensure_ascii=False),
        "--as", "user",
    ]
    _lark(args)
    return len(records)


def _create_one(base_token: str, table_id: str, record: dict) -> str:
    """创建一条记录，返回 record_id。"""
    clean = {k: v for k, v in record.items() if v not in (None, "", [])}
    args = [
        "base", "+record-batch-create",
        "--base-token", base_token,
        "--table-id", table_id,
        "--json", json.dumps({"create_records": [clean]}, ensure_ascii=False),
        "--as", "user",
    ]
    data = _lark(args)
    ids = ((data.get("data") or {}).get("record_id_list")) or []
    return ids[0] if ids else ""


def _update_records(base_token: str, table_id: str, updates: Dict[str, dict], dry_run: bool) -> int:
    if not updates:
        return 0
    payload = {"update_records": updates}
    if dry_run:
        print(json.dumps(payload, ensure_ascii=False)[:4000])
        return len(updates)
    args = [
        "base", "+record-batch-update",
        "--base-token", base_token,
        "--table-id", table_id,
        "--json", json.dumps(payload, ensure_ascii=False),
        "--as", "user",
    ]
    _lark(args)
    return len(updates)


def sync_companies(store: Store, cfg: dict, run_date: str,
                   dry_run: bool = False) -> int:
    """把当天新岗位按公司聚合，写进「投递记录」表：一行一个公司。

    - 岗位只作为备注里的线索；不写「岗位名称」。
    - 一个公司只建一条记录；后续发现该公司新岗位不重复建行。
    - 已存在于表里的公司（你手工维护的）不覆盖。
    """
    feishu = cfg.get("feishu", {})
    if not feishu.get("enabled") and not dry_run:
        return 0
    base_token = feishu.get("application_base_token", "")
    table_id = feishu.get("application_table_id", "")
    if not base_token or not table_id:
        print("飞书投递记录未配置 application_base_token/application_table_id，跳过写入。")
        return 0
    jobs = store.list_jobs(first_seen=run_date)
    if not jobs:
        return 0

    try:
        _, rows = _table_rows(base_token, table_id)
        existing_companies = {
            str(row.get("公司") or "").strip()
            for row in rows if str(row.get("公司") or "").strip()
        }
    except Exception:
        existing_companies = set()

    groups: Dict[str, List[dict]] = {}
    for job in jobs:
        company_id = str(job.get("company_id") or job.get("company_name") or "")
        if not company_id:
            continue
        groups.setdefault(company_id, []).append(job)

    creates: List[tuple] = []
    skipped = 0
    for company_id, group in groups.items():
        company = str(group[0].get("company_name") or "").strip()
        if not company:
            continue
        if store.is_company_synced(company_id, table_id):
            skipped += 1
            continue
        if company in existing_companies:
            store.mark_company_synced(company_id, table_id, "")
            skipped += 1
            continue
        payload = _company_payload(group)
        if not payload:
            continue
        creates.append((company_id, payload))

    if dry_run:
        _create_records(base_token, table_id, [p for _, p in creates], True)
        return len(creates)

    created = 0
    failed = []
    for company_id, payload in creates:
        try:
            rid = _create_one(base_token, table_id, payload)
            if rid:
                store.mark_company_synced(company_id, table_id, rid)
                created += 1
            else:
                failed.append((payload.get("公司"), "record_id 为空"))
        except Exception as exc:
            failed.append((payload.get("公司"), str(exc)[:160]))
    if created:
        print(f"飞书投递记录：新增 {created} 个公司（已存在/已同步跳过 {skipped} 个，岗位名称留空）。")
    for company, err in failed[:5]:
        print(f"  写入失败：{company}：{err}")
    return created


def sync_new_jobs(store: Store, cfg: dict, run_date: str,
                  dry_run: bool = False) -> int:
    """兼容旧调用名；实际按公司写入。"""
    return sync_companies(store, cfg, run_date, dry_run)


def load_applications(cfg: dict) -> List[dict]:
    feishu = cfg.get("feishu", {})
    base_token = feishu.get("application_base_token", "")
    table_id = feishu.get("application_table_id", "")
    if not base_token or not table_id:
        return []
    try:
        _, rows = _table_rows(base_token, table_id)
    except Exception as exc:
        print(f"读取投递记录失败：{exc}")
        return []
    return rows


def sync_report_doc(cfg: dict, report_path: str) -> bool:
    """把日报 Markdown 覆盖写入飞书「秋招岗位雷达日报」文档。"""
    feishu = cfg.get("feishu", {})
    if not feishu.get("enabled"):
        return False
    doc = feishu.get("report_doc_token", "")
    if not doc:
        return False
    exe = shutil.which("lark-cli")
    if not exe:
        return False
    with open(os.path.expanduser(report_path), encoding="utf-8") as f:
        content = f.read()
    p = subprocess.run(
        [exe, "docs", "+update", "--doc", doc, "--command", "overwrite",
         "--doc-format", "markdown", "--content", "-", "--as", "user"],
        input=content, capture_output=True, text=True, timeout=120,
    )
    if p.returncode != 0:
        print(f"飞书日报写入失败：{p.stderr.strip()[:400]}")
        return False
    return True


def application_stats(rows: List[dict]) -> dict:
    counts: Dict[str, int] = {}
    upcoming = []
    for row in rows:
        status = row.get("投递状态")
        if isinstance(status, list):
            status = status[0] if status else ""
        status = str(status or "未填")
        counts[status] = counts.get(status, 0) + 1
        next_date = str(row.get("下一步日期") or "")[:10]
        if next_date:
            upcoming.append({
                "公司": row.get("公司", ""),
                "岗位名称": row.get("岗位名称", ""),
                "下一步": row.get("下一步", ""),
                "下一步日期": next_date,
                "投递状态": status,
            })
    upcoming.sort(key=lambda x: x["下一步日期"])
    return {"counts": counts, "upcoming": upcoming, "total": len(rows)}
