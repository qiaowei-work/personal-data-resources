"""用 ego-browser 打开需要登录的平台，并把浏览器交给用户。

用法：
  python3 scripts/radar.py login
  python3 scripts/radar.py login --platforms boss,zhaopin,51job

登录后用户回复「继续」，下一轮用 takeOverTaskSpace(spaceId) 接管，
再检查登录态并接抓取适配器。
"""
from __future__ import annotations

import json
import subprocess
from typing import List

SPACE_NAME = "qiuzhao-radar-login"
PLATFORMS = {
    "boss": ("BOSS直聘", "https://www.zhipin.com/"),
    "zhaopin": ("智联招聘", "https://www.zhaopin.com/"),
    "51job": ("前程无忧", "https://www.51job.com/"),
    "liepin": ("猎聘", "https://www.liepin.com/"),
}


def build_script(keys: List[str]) -> str:
    targets = []
    for idx, key in enumerate(keys):
        label = "p1" if idx == 0 else f"p{idx + 1}"
        name, url = PLATFORMS[key]
        targets.append({"label": label, "name": name, "url": url})
    lines = [
        f'const task = await taskSpace("{SPACE_NAME}");',
        'console.log(JSON.stringify({ spaceId: task.spaceId }));',
        "const targets = " + json.dumps(targets, ensure_ascii=False) + ";",
        "for (const target of targets) {",
        '  const page = target.label === "p1" ? task.page("p1") : await task.newPage();',
        "  await page.goto(target.url);",
        '  console.log(target.label, target.name, await page.url(), await page.title());',
        "}",
        "await task.handOff();",
        'console.log("HANDOFF: 请登录以上平台，完成后回复「继续」。");',
    ]
    return "\n".join(lines)


def run(platforms: str = "boss,zhaopin,51job") -> int:
    keys = [x.strip() for x in platforms.split(",") if x.strip() in PLATFORMS]
    if not keys:
        print("没有可登录的平台。")
        return 1
    script = build_script(keys)
    p = subprocess.run(
        ["ego-browser", "nodejs"], input=script, capture_output=True, text=True, timeout=180
    )
    print(p.stdout[-3000:])
    if p.returncode != 0:
        err = p.stderr[-2000:]
        if "Control of this task space is with the user" in err:
            print("浏览器任务空间已经在用户手里，请直接登录，完成后回复「继续」。")
        else:
            print(err)
        return p.returncode
    return 0
