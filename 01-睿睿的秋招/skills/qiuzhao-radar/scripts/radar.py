#!/usr/bin/env python3
"""秋招岗位雷达 CLI。

常用：
  python3 scripts/radar.py init
  python3 scripts/radar.py collect --keywords 化工,材料 --pages 2 --days 30
  python3 scripts/radar.py collect --schools 四川大学,成都大学 --no-events
  python3 scripts/radar.py report
  python3 scripts/radar.py schools
  python3 scripts/radar.py export --format csv
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from typing import Dict, List, Optional

try:
    from . import ats, feishu, iguopin, login, ncss, normalize, report, scbdc, sicau
    from .store import Store
except ImportError:  # python3 scripts/radar.py
    import ats
    import feishu
    import iguopin
    import login
    import ncss
    import normalize
    import report
    import scbdc
    import sicau
    from store import Store

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(SKILL_DIR, "data")
DEFAULT_CONFIG_PATH = os.path.expanduser("~/.qiuzhao-radar/config.json")
DEFAULT_DB = os.path.expanduser("~/.qiuzhao-radar/radar.db")
ALIAS_PATH = os.path.join(DATA_DIR, "company_aliases.json")
SCHOOLS_PATH = os.path.join(DATA_DIR, "chengdu_schools.json")


def load_config(path: str) -> dict:
    cfg = normalize.load_config(path)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(os.path.expanduser(path)), exist_ok=True)
        with open(os.path.expanduser(path), "w", encoding="utf-8") as f:
            json.dump(normalize.DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    return cfg


def load_schools() -> List[dict]:
    if not os.path.exists(SCHOOLS_PATH):
        return []
    with open(SCHOOLS_PATH, encoding="utf-8") as f:
        return json.load(f)


def select_schools(cfg: dict, spec: Optional[str], max_schools: int = 0) -> List[dict]:
    schools = load_schools()
    include_research = cfg.get("include_research_institutes", False)
    selected = []
    for school in schools:
        if not school.get("enabled", True):
            continue
        if school.get("type") == "research_institute" and not include_research:
            continue
        if not school.get("scbdc_id"):
            continue
        if not spec or spec == "all":
            selected.append(school)
            continue
        wanted = {x.strip() for x in spec.split(",") if x.strip()}
        if school.get("name") in wanted or str(school.get("scbdc_id")) in wanted:
            selected.append(school)
    if max_schools > 0:
        selected = selected[:max_schools]
    return selected


def _stats() -> Dict[str, dict]:
    return {
        "scbdc": {"ok": 0, "new": 0, "merged": 0, "events": 0, "error": ""},
        "sicau": {"ok": 0, "new": 0, "merged": 0, "events": 0, "error": ""},
        "ncss": {"ok": 0, "new": 0, "merged": 0, "filtered": 0, "events": 0, "error": ""},
        "iguopin": {"ok": 0, "new": 0, "merged": 0, "filtered": 0, "events": 0, "error": ""},
        "ats": {"ok": 0, "new": 0, "merged": 0, "filtered": 0, "events": 0, "error": ""},
    }


def collect_scbdc(store: Store, cfg: dict, args, stats: dict):
    if not cfg.get("scbdc", {}).get("enabled", True):
        return
    keywords = args.keywords.split(",") if args.keywords else cfg.get("keywords", [])
    keywords = [k.strip() for k in keywords if k.strip()]
    pages = args.pages or int(cfg.get("scbdc", {}).get("max_pages", 2))
    days = args.days or int(cfg.get("scbdc", {}).get("days", 30))
    for keyword in keywords:
        try:
            batch = scbdc.fetch_jobs(keyword, max_pages=pages, days=days)
        except Exception as exc:  # 单关键词失败不影响其他关键词
            stats["scbdc"]["error"] = f"{keyword}: {exc}"
            continue
        stats["scbdc"]["ok"] += len(batch)
        for record in batch:
            job = normalize.prepare_job(record, cfg)
            _, is_new, merged = store.upsert_job(job)
            stats["scbdc"]["new"] += 1 if is_new else 0
            stats["scbdc"]["merged"] += 1 if merged else 0

    if args.no_events:
        return
    schools = select_schools(cfg, args.schools, args.max_schools)
    event_types = cfg.get("scbdc", {}).get("event_types", ["campus", "jobfair", "teachin"])
    event_pages = int(cfg.get("scbdc", {}).get("event_pages", 1))
    event_days = int(args.event_days or cfg.get("scbdc", {}).get("event_days", 60))
    for school in schools:
        try:
            events = scbdc.fetch_school_events(
                school["scbdc_id"], school["name"],
                event_types=event_types, max_pages=event_pages, days=event_days,
            )
        except Exception as exc:
            stats["scbdc"]["error"] = f"{school['name']}: {exc}"
            continue
        for event in events:
            store.upsert_event(normalize.prepare_event(event))
        stats["scbdc"]["events"] += len(events)


def collect_sicau(store: Store, cfg: dict, args, stats: dict):
    if not cfg.get("sicau", {}).get("enabled", True):
        return
    max_pages = args.pages or int(cfg.get("sicau", {}).get("max_pages", 1))
    page_size = int(cfg.get("sicau", {}).get("page_size", 50))
    try:
        events = sicau.fetch_events(max_pages=max_pages, page_size=page_size)
    except Exception as exc:
        stats["sicau"]["error"] = str(exc)
        return
    for event in events:
        store.upsert_event(normalize.prepare_event(event))
    stats["sicau"]["ok"] = len(events)
    stats["sicau"]["events"] = len(events)


def collect_ncss(store: Store, cfg: dict, args, stats: dict):
    conf = cfg.get("ncss", {})
    if not conf.get("enabled", True):
        return
    max_pages = args.pages or int(conf.get("max_pages", 5))
    page_size = int(conf.get("page_size", 20))
    properties = conf.get("properties") or ncss.DEFAULT_PROPERTIES
    try:
        raw_items = ncss.fetch_jobs(properties, max_pages=max_pages, page_size=page_size)
    except Exception as exc:
        stats["ncss"]["error"] = str(exc)
        return
    for item in raw_items:
        record = ncss.to_record(item)
        if not normalize.is_topic_relevant(record, cfg) or \
                normalize.job_family(record.get("title", ""), record.get("description", "")) == "non_target":
            stats["ncss"]["filtered"] += 1
            continue
        job = normalize.prepare_job(record, cfg)
        _, is_new, merged = store.upsert_job(job)
        stats["ncss"]["new"] += 1 if is_new else 0
        stats["ncss"]["merged"] += 1 if merged else 0
    stats["ncss"]["ok"] = len(raw_items)


def collect_iguopin(store: Store, cfg: dict, args, stats: dict):
    conf = cfg.get("iguopin", {})
    if not conf.get("enabled", True):
        return
    max_pages = args.pages or int(conf.get("max_pages", 20))
    campus_only = bool(conf.get("campus_only", True))
    try:
        raw_items = iguopin.fetch_jobs(max_pages=max_pages, campus_only=campus_only)
    except Exception as exc:
        stats["iguopin"]["error"] = str(exc)
        return
    for item in raw_items:
        record = iguopin.to_record(item)
        if not normalize.is_topic_relevant(record, cfg) or \
                normalize.job_family(record.get("title", ""), record.get("description", "")) == "non_target":
            stats["iguopin"]["filtered"] += 1
            continue
        job = normalize.prepare_job(record, cfg)
        _, is_new, merged = store.upsert_job(job)
        stats["iguopin"]["new"] += 1 if is_new else 0
        stats["iguopin"]["merged"] += 1 if merged else 0
    stats["iguopin"]["ok"] = len(raw_items)


def collect_ats(store: Store, cfg: dict, args, stats: dict):
    conf = cfg.get("ats", {})
    if not conf.get("enabled", True):
        return
    path = os.path.join(DATA_DIR, "target_companies.json")
    try:
        companies = ats.load_companies(path)
    except Exception as exc:
        stats["ats"]["error"] = str(exc)
        return
    pages = args.pages or int(conf.get("max_pages", 3))
    only = getattr(args, "ats_company", "")
    for entry in companies:
        if not entry.get("enabled", True):
            continue
        if only and only not in (entry.get("name"), entry.get("ats_ref")):
            continue
        typ = entry.get("ats_type", "unknown")
        if typ in ("unknown", "hotjob"):
            stats["ats"]["filtered"] += 1
            continue
        try:
            raw_items = ats.fetch_company(entry, pages=pages)
        except Exception as exc:
            stats["ats"]["error"] = f"{entry.get('name')}: {exc}"
            continue
        stats["ats"]["ok"] += len(raw_items)
        for record in raw_items:
            job = normalize.prepare_job(record, cfg)
            _, is_new, merged = store.upsert_job(job)
            stats["ats"]["new"] += 1 if is_new else 0
            stats["ats"]["merged"] += 1 if merged else 0


def cmd_login(args):
    raise SystemExit(login.run(args.platforms))


def cmd_ats_discover(args):
    typ, ref = ats.discover(args.url)
    print(f"识别结果：ats_type={typ} ats_ref={ref}")
    if args.company and typ != "unknown":
        path = os.path.join(DATA_DIR, "target_companies.json")
        companies = ats.load_companies(path)
        hit = False
        for entry in companies:
            if entry.get("name") == args.company:
                entry["ats_type"] = typ
                entry["ats_ref"] = ref
                entry["careers_url"] = args.url
                hit = True
        with open(path, "w", encoding="utf-8") as f:
            json.dump(companies, f, ensure_ascii=False, indent=2)
        print(f"已更新 {args.company}（{hit}）")
    elif typ == "unknown":
        print("未识别；把招聘门户 URL 发给我，或手动在 target_companies.json 里填 ats_type/ats_ref。")


def cmd_init(args):
    cfg_path = os.path.expanduser(args.config)
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    if not os.path.exists(cfg_path):
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(normalize.DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        print(f"已创建配置：{cfg_path}")
    else:
        print(f"配置已存在：{cfg_path}")
    data_dir = os.path.expanduser(normalize.DEFAULT_CONFIG["data_dir"])
    os.makedirs(os.path.join(data_dir, "reports"), exist_ok=True)
    print(f"数据目录：{data_dir}")
    print("下一步：编辑配置里的 target_cities / majors / keywords，然后运行 collect。")


def cmd_schools(args):
    schools = load_schools()
    if args.refresh:
        try:
            options = scbdc.fetch_school_options()
            print(f"川e就当前学校/院所选项：{len(options)} 个")
        except Exception as exc:
            print(f"读取川e就学校列表失败：{exc}")
    for school in schools:
        print(
            f"{school.get('scbdc_id') or '-':>7}  {school.get('name'):<22} "
            f"{school.get('type', ''):<16} {school.get('adapter', ''):<8} "
            f"{'启用' if school.get('enabled', True) else '停用'}"
        )


def cmd_collect(args):
    cfg = load_config(os.path.expanduser(args.config))
    data_dir = os.path.expanduser(args.data_dir or cfg.get("data_dir", "~/.qiuzhao-radar"))
    db_path = os.path.join(data_dir, "radar.db")
    store = Store(db_path, alias_path=ALIAS_PATH if os.path.exists(ALIAS_PATH) else None)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_date = date.today().isoformat()
    stats = _stats()
    store.start_run(run_id)
    try:
        if args.source in ("scbdc", "all"):
            collect_scbdc(store, cfg, args, stats)
        if args.source in ("sicau", "all"):
            collect_sicau(store, cfg, args, stats)
        if args.source in ("ncss", "all"):
            collect_ncss(store, cfg, args, stats)
        if args.source in ("iguopin", "all"):
            collect_iguopin(store, cfg, args, stats)
        if args.source in ("ats", "all"):
            collect_ats(store, cfg, args, stats)
        closed = store.close_expired()
        stats["closed_expired"] = closed
        store.finish_run(run_id, stats)
        print(f"运行完成：{run_id}")
        for source, stat in stats.items():
            if isinstance(stat, dict):
                print(
                    f"  {source}: 抓取 {stat.get('ok', 0)} / 新增 {stat.get('new', 0)} / "
                    f"合并去重 {stat.get('merged', 0)} / 主题过滤 {stat.get('filtered', 0)} / "
                    f"事件 {stat.get('events', 0)}"
                    + (f" / 错误 {stat['error']}" if stat.get("error") else "")
                )
        if not args.no_report:
            apps = feishu.load_applications(cfg)
            path = report.write_report(store, cfg, run_date, stats, apps)
            print(f"日报：{path}")
            if not args.no_feishu and feishu.sync_report_doc(cfg, path):
                print("飞书日报已更新。")
        if not args.no_feishu:
            feishu.sync_new_jobs(store, cfg, run_date)
    finally:
        store.close()


def cmd_report(args):
    cfg = load_config(os.path.expanduser(args.config))
    data_dir = os.path.expanduser(args.data_dir or cfg.get("data_dir", "~/.qiuzhao-radar"))
    store = Store(os.path.join(data_dir, "radar.db"),
                  alias_path=ALIAS_PATH if os.path.exists(ALIAS_PATH) else None)
    try:
        apps = feishu.load_applications(cfg)
        path = report.write_report(
            store, cfg, args.date or date.today().isoformat(),
            store.latest_run_stats(), apps
        )
        print(path)
        if feishu.sync_report_doc(cfg, path):
            print("飞书日报已更新。")
    finally:
        store.close()


def cmd_feishu_preview(args):
    cfg = load_config(os.path.expanduser(args.config))
    data_dir = os.path.expanduser(args.data_dir or cfg.get("data_dir", "~/.qiuzhao-radar"))
    store = Store(os.path.join(data_dir, "radar.db"),
                  alias_path=ALIAS_PATH if os.path.exists(ALIAS_PATH) else None)
    try:
        n = feishu.sync_new_jobs(
            store, cfg, args.date or date.today().isoformat(), dry_run=True
        )
        print(f"\n预览记录数：{n}")
    finally:
        store.close()


def cmd_export(args):
    cfg = load_config(os.path.expanduser(args.config))
    data_dir = os.path.expanduser(args.data_dir or cfg.get("data_dir", "~/.qiuzhao-radar"))
    store = Store(os.path.join(data_dir, "radar.db"),
                  alias_path=ALIAS_PATH if os.path.exists(ALIAS_PATH) else None)
    try:
        out = args.output or os.path.join(data_dir, "export.csv")
        if args.format == "csv":
            path = store.export_csv(out)
        else:
            path = os.path.join(data_dir, "export.json")
            jobs = store.list_jobs(first_seen=args.date)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(jobs, f, ensure_ascii=False, indent=2)
        print(path)
    finally:
        store.close()


def build_parser():
    parser = argparse.ArgumentParser(description="秋招岗位雷达")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="配置文件路径")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="初始化配置和数据目录")
    p_init.set_defaults(func=cmd_init)

    p_schools = sub.add_parser("schools", help="列出成都高校源")
    p_schools.add_argument("--refresh", action="store_true", help="顺便读取川e就学校选项")
    p_schools.set_defaults(func=cmd_schools)

    p_collect = sub.add_parser("collect", help="抓取并增量合并")
    p_collect.add_argument("--source", choices=["scbdc", "sicau", "ncss", "iguopin", "ats", "all"], default="all")
    p_collect.add_argument("--ats-company", help="只抓某一家已映射 ATS 的公司")
    p_collect.add_argument("--keywords", help="逗号分隔，覆盖配置")
    p_collect.add_argument("--pages", type=int, default=0, help="每个关键词最多抓几页")
    p_collect.add_argument("--days", type=int, default=0, help="只抓最近 N 天发布的岗位")
    p_collect.add_argument("--schools", help="all 或逗号分隔的学校名/川e就ID")
    p_collect.add_argument("--max-schools", type=int, default=0, help="调试用：最多抓几所学校的事件")
    p_collect.add_argument("--event-days", type=int, default=0)
    p_collect.add_argument("--no-events", action="store_true", help="只抓岗位，不抓宣讲会/招聘会")
    p_collect.add_argument("--no-report", action="store_true", help="抓完不生成日报")
    p_collect.add_argument("--no-feishu", action="store_true", help="不写飞书 Base（默认配置关闭时也不会写）")
    p_collect.add_argument("--data-dir", help="覆盖数据目录")
    p_collect.set_defaults(func=cmd_collect)

    p_report = sub.add_parser("report", help="生成 Markdown 日报")
    p_report.add_argument("--date", help="日报日期 YYYY-MM-DD")
    p_report.add_argument("--data-dir", help="覆盖数据目录")
    p_report.set_defaults(func=cmd_report)

    p_login = sub.add_parser("login", help="用 ego-browser 打开 BOSS/智联/51job 登录页")
    p_login.add_argument("--platforms", default="boss,zhaopin,51job",
                         help="逗号分隔：boss,zhaopin,51job,liepin")
    p_login.set_defaults(func=cmd_login)

    p_discover = sub.add_parser("ats-discover", help="从招聘门户 URL 识别 ATS 并写回公司清单")
    p_discover.add_argument("--url", required=True)
    p_discover.add_argument("--company")
    p_discover.set_defaults(func=cmd_ats_discover)

    p_preview = sub.add_parser("feishu-preview", help="预览飞书 Base 写入 JSON")
    p_preview.add_argument("--date", help="只预览某天首次发现的岗位")
    p_preview.add_argument("--data-dir", help="覆盖数据目录")
    p_preview.set_defaults(func=cmd_feishu_preview)

    p_export = sub.add_parser("export", help="导出 CSV/JSON")
    p_export.add_argument("--format", choices=["csv", "json"], default="csv")
    p_export.add_argument("--output", help="输出路径")
    p_export.add_argument("--date", help="只导出某天首次发现的岗位")
    p_export.add_argument("--data-dir", help="覆盖数据目录")
    p_export.set_defaults(func=cmd_export)
    return parser


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
