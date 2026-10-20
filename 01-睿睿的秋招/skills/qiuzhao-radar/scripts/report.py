"""生成每日 Markdown 简报。"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

try:
    from .store import Store
except ImportError:  # python3 scripts/radar.py
    from store import Store


def _cell(value) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _link(url: str, text: str = "打开") -> str:
    return f"[{text}]({url})" if url else ""


def _job_row(job: dict) -> str:
    reasons = "；".join(job.get("reasons", []))
    return " | ".join([
        _cell(job.get("company_name")),
        _cell(job.get("title")),
        _cell(job.get("city")),
        _cell(job.get("education")),
        _cell(job.get("grad_year")),
        _cell(job.get("deadline") or "未注明"),
        _cell(job.get("recommendation")),
        _cell(reasons),
        _cell(job.get("source")),
        _link(job.get("url", "")),
    ])


def _table(jobs: List[dict], empty_text: str = "今日无新增。") -> str:
    if not jobs:
        return empty_text + "\n"
    lines = [
        "| 公司 | 岗位 | 城市 | 学历 | 届别 | 截止 | 判定 | 原因/备注 | 来源 | 链接 |",
        "|-|-|-|-|-|-|-|-|-|-|",
    ]
    lines.extend("| " + _job_row(j) + " |" for j in jobs)
    return "\n".join(lines) + "\n"


def generate_report(store: Store, cfg: dict, run_date: Optional[str] = None,
                    run_stats: Optional[Dict[str, dict]] = None,
                    applications: Optional[List[dict]] = None) -> str:
    run_date = run_date or date.today().isoformat()
    new_jobs = store.list_jobs(first_seen=run_date)
    actionable = [j for j in new_jobs if j.get("recommendation") == "可投"]
    review = [j for j in new_jobs if j.get("recommendation") == "待核实"]
    remote = [j for j in new_jobs if j.get("recommendation") == "异地"]
    excluded = [j for j in new_jobs if j.get("recommendation") == "不推荐"]

    deadline_soon = []
    cutoff = (date.today() + timedelta(days=7)).isoformat()
    for job in store.list_jobs(recommendations=["可投", "待核实", "异地"]):
        d = job.get("deadline")
        if d and date.today().isoformat() <= d <= cutoff:
            deadline_soon.append(job)
    deadline_soon.sort(key=lambda j: j.get("deadline") or "")

    events = store.list_events(upcoming=True, limit=80)
    exclusion_counts = store.exclusion_counts(first_seen=run_date)

    lines = [
        f"# 秋招岗位雷达 · {run_date}",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 数据源：川e就（成都高校就业信息）、四川农业大学就业网、国家大学生就业服务平台（NCSS）、国聘公开推荐池、企业官方 ATS（已映射公司）",
        f"- 目标：{cfg.get('grad_year')} 届校招正式岗；base 地 {('、'.join(cfg.get('target_cities', [])) or '未设置')}（不做硬过滤）",
        f"- 今日累计新增（按首次发现日期）：{len(new_jobs)} 条（可投 {len(actionable)} / 待核实 {len(review)} / 异地 {len(remote)} / 不推荐 {len(excluded)}）",
    ]
    if run_stats:
        run_new = sum(
            stat.get("new", 0) for stat in run_stats.values() if isinstance(stat, dict)
        )
        lines.append(f"- 本次运行新增：{run_new} 条；重复运行不会重复计数（看下方源健康）")
    lines += [
        "",
        "## 一、今日累计新增 · 可投",
        "",
        _table(actionable),
        "## 二、今日累计新增 · 待核实",
        "",
        _table(review, "今日无待核实的新增。"),
        "## 三、今日累计新增 · 异地高匹配",
        "",
        _table(remote, "今日无异地新增。"),
        "## 四、7 天内截止",
        "",
    ]
    if deadline_soon:
        lines += [
            "| 公司 | 岗位 | 城市 | 截止 | 判定 | 链接 |",
            "|-|-|-|-|-|-|",
        ]
        for job in deadline_soon:
            lines.append("| " + " | ".join([
                _cell(job.get("company_name")), _cell(job.get("title")),
                _cell(job.get("city")), _cell(job.get("deadline")),
                _cell(job.get("recommendation")), _link(job.get("url", "")),
            ]) + " |")
        lines.append("")
    else:
        lines += ["当前没有抓到 7 天内截止的岗位（很多岗位未注明截止日期）。", ""]

    lines += ["## 五、宣讲会 / 招聘会", ""]
    if events:
        lines += [
            "| 日期 | 学校 | 类型 | 标题 | 地点 | 链接 |",
            "|-|-|-|-|-|-|",
        ]
        for ev in events:
            lines.append("| " + " | ".join([
                _cell(ev.get("event_date")), _cell(ev.get("school")),
                _cell(ev.get("event_type")), _cell(ev.get("title")),
                _cell(ev.get("location")), _link(ev.get("url", "")),
            ]) + " |")
        lines.append("")
    else:
        lines += ["暂无未来宣讲会/招聘会数据。", ""]

    lines += ["## 六、投递进度（来自飞书「简历投递记录」）", ""]
    if applications:
        counts = {}
        upcoming = []
        for row in applications:
            status = row.get("投递状态")
            if isinstance(status, list):
                status = status[0] if status else ""
            status = str(status or "未填")
            counts[status] = counts.get(status, 0) + 1
            next_date = str(row.get("下一步日期") or "")[:10]
            if next_date:
                upcoming.append((next_date, row, status))
        lines += ["| 状态 | 数量 |", "|-|-|"]
        for status, count in sorted(counts.items(), key=lambda x: -x[1]):
            lines.append(f"| {_cell(status)} | {count} |")
        lines.append("")
        upcoming.sort(key=lambda x: x[0])
        if upcoming:
            lines += ["| 下一步日期 | 公司 | 岗位 | 当前状态 | 下一步 |",
                      "|-|-|-|-|-|"]
            for d, row, status in upcoming[:10]:
                lines.append("| " + " | ".join([
                    _cell(d), _cell(row.get("公司")), _cell(row.get("岗位名称")),
                    _cell(status), _cell(row.get("下一步")),
                ]) + " |")
            lines.append("")
    else:
        lines += ["未读取到投递记录（或飞书权限/配置未生效）。", ""]

    lines += ["## 七、排除统计（今日新增）", ""]
    if exclusion_counts:
        lines += ["| 原因 | 数量 |", "|-|-|"]
        for reason, count in sorted(exclusion_counts.items(), key=lambda x: -x[1]):
            lines.append(f"| {_cell(reason)} | {count} |")
        lines.append("")
    else:
        lines += ["今日没有新增被排除的岗位。", ""]

    lines += ["## 八、数据源健康", ""]
    if run_stats:
        lines += ["| 来源 | 抓取 | 新增岗位 | 合并去重 | 主题过滤 | 事件 | 错误 |",
                  "|-|-|-|-|-|-|-|"]
        for source, stat in run_stats.items():
            if not isinstance(stat, dict):
                continue
            lines.append(
                f"| {_cell(source)} | {stat.get('ok', 0)} | {stat.get('new', 0)} | "
                f"{stat.get('merged', 0)} | {stat.get('filtered', 0)} | "
                f"{stat.get('events', 0)} | {_cell(stat.get('error', ''))} |"
            )
        lines.append("")
    else:
        lines += ["本次运行未提供源统计。", ""]

    lines += [
        "## 九、数据说明与限制",
        "",
        "- 川e就是四川省教育厅平台，学校公告/招聘会来自各校上报；**平台在招 ≠ 企业 ATS 已核验**，投递前请打开链接确认。",
        "- 川农大是直连公开 JSON API；川大、电子科大、西南交大等直连站有 WAF/登录态，当前由川e就学校筛选覆盖，未逐个写爬虫。",
        "- 平台职位列表自带 JD 摘要；部分岗位未注明届别/学历/截止，因此进入「待核实」，不是漏抓。",
        "- 去重按「公司 + 二级单位 + 岗位名 + 城市 + 届别」，公司名只做公司级归并，不会把同公司不同岗位合并。",
        "- 本 skill 只采集和整理，**不登录、不自动投递、不点提交**。",
        "",
    ]
    return "\n".join(lines)


def write_report(store: Store, cfg: dict, run_date: Optional[str] = None,
                 run_stats: Optional[Dict[str, dict]] = None,
                 applications: Optional[List[dict]] = None) -> str:
    run_date = run_date or date.today().isoformat()
    data_dir = os.path.expanduser(cfg.get("data_dir", "~/.qiuzhao-radar"))
    report_dir = os.path.join(data_dir, "reports")
    os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, f"{run_date}.md")
    content = generate_report(store, cfg, run_date, run_stats, applications)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
