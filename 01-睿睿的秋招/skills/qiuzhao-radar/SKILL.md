---
name: qiuzhao-radar
description: 秋招岗位雷达：采集成都高校就业网（川e就 + 川农大直连）、NCSS、国聘、企业官方 ATS（北森/Moka/飞书），脚本增量去重，按 2027 届校招正式岗筛选，按公司聚合写入飞书「投递记录」（一行一个公司），并生成带岗位明细和投递进度的本地日报。当用户说"跑一下岗位雷达""今天有什么新岗位""成都高校就业网有什么岗位""国聘/NCSS 有什么岗位""更新投递记录""查宣讲会/招聘会""这个岗位重复了吗"时使用。
---

# 秋招岗位雷达

## 定位

**只做采集、归一化、去重、初筛和日报；不代登录、不自动投递、不点提交。需要登录的平台由你本人登录，登录态留在 ego-browser。**

当前覆盖的渠道：

- **学校源**
  - **川e就—四川大学生就业服务平台**（四川省教育厅）：平台职位、学校招聘公告、宣讲会、招聘会。通过 `universityid` 覆盖成都高校。
  - **四川农业大学就业信息网**：直连公开 JSON API，作为学校直连示例。
  - **成都高校清单**：`data/chengdu_schools.json`，含 62 所成都高校/职业院校，以及默认停用的在蓉科研院所。
- **官方聚合源**
  - **国家大学生就业服务平台（NCSS）**：教育部平台，公开匿名接口；当前按单位性质抓取，并做主题预过滤。
  - **国聘网**：只用公开推荐池接口（约 400 条），抓校园招聘/实习；完整搜索接口需要登录态，暂不做。
- **企业官方 ATS**
  - **北森**：`{slug}.zhiye.com`，公开 `GetJobAdPageList`。
  - **Moka**：`app.mokahr.com/campus-recruitment/{orgId}/{siteId}`，AES 响应解密。
  - **飞书招聘**：`{host}.jobs.feishu.cn`，公开 `/api/v1/search/job/posts`。
  - **hotjob**（万华/伊利等）：先识别、标记为待适配。
  - 公司清单：`data/target_companies.json`（60 家候选；已有 ATS 映射会抓，未映射的跳过）。

川大、电子科大、西南交大、成都大学等直连站存在 WAF / 登录态 / 反爬，当前不逐个硬爬，统一走川e就的学校筛选；清单里保留直连 URL 和状态，后续可按需补适配器。

**登录平台（BOSS/智联/51job）**：ego-browser 登录流程已准备好；抓取适配要等登录后按真实页面接。当前不进入每日自动流，避免半成品数据。

## 快速开始

```bash
cd skills/qiuzhao-radar
python3 scripts/radar.py init
# 编辑 ~/.qiuzhao-radar/config.json 里的 target_cities / majors / keywords

# 第一次：少量验证（学校源）
python3 scripts/radar.py collect --source scbdc --keywords 化工,2027届 --pages 1 --days 30 --no-events

# 单独验证 NCSS / 国聘
python3 scripts/radar.py collect --source ncss --pages 1 --no-events
python3 scripts/radar.py collect --source iguopin --pages 1 --no-events

# 单独验证 ATS（只抓已映射公司）
python3 scripts/radar.py collect --source ats --ats-company 宁德时代 --pages 1 --no-events

# 日常：学校 + NCSS + 国聘 + 已映射 ATS + 学校事件
python3 scripts/radar.py collect --source all --pages 3 --days 30

# 看日报
python3 scripts/radar.py report
# 导出 CSV
python3 scripts/radar.py export --format csv
```

**依赖**：Python 3.9+ 和系统 `curl`。不需要第三方 Python 包。

## 入口

| 说法 | 命令 | 说明 |
|-|-|-|
| 跑今天的雷达 | `collect --source all --pages 3 --days 30` | 默认按配置关键词抓岗位 + 学校事件 |
| 只看某几个词 | `collect --keywords 化工,材料,2027届 --pages 2` | 覆盖配置 |
| 只看某几所学校的事件 | `collect --schools 四川大学,成都大学 --no-events` | `--no-events` 时只抓岗位 |
| 只看 NCSS | `collect --source ncss --pages 2 --no-events` | 全国校招 |
| 只看国聘 | `collect --source iguopin --pages 5 --no-events` | 央企推荐池，最多约 20 页 |
| 只看岗位不抓事件 | `collect --no-events` | 最快 |
| 生成日报 | `report` | 默认今天，`--date YYYY-MM-DD` 可指定 |
| 列出学校源 | `schools` | `--refresh` 顺便读川e就当前学校选项 |
| 导出 | `export --format csv` | 也可 `json` |
| 检查重复 | `python3 -m unittest discover -s tests` | 去重/门槛测试 |

## 数据源与学校清单

详见 `references/source-channels.md`。

关键规则：

1. **川e就/NCSS/国聘都是“平台在招”，不是企业 ATS。** 岗位状态以链接打开后的页面为准；日报标 `platform_verified` 只是“平台在招”，不是“企业已核验”。
2. **学校直连站只在公开、无需登录时接入。** 有 WAF/登录态的学校不绕，走川e就。
3. **NCSS/国聘是宽口径池子，先做主题预过滤。** 用 `topic_keywords` / `strong_topic_keywords` 过滤，避免把银行、销售、IT、施工岗都入库；过滤数会显示在日报「数据源健康」里。
4. **频率**：每日一次即可；同一来源请求间隔 ≥0.6 秒；失败重试一次，不并发轰炸。
5. **新增学校**：在 `data/chengdu_schools.json` 加一条；`scbdc_id` 从 `schools --refresh` 或川e就学校下拉框取；没有 `scbdc_id` 的标 `manual`，不要猜。

## 去重（脚本实现）

详见 `references/dedupe.md`。核心是三层：

| 层 | Key | 用途 |
|-|-|-|
| 来源级 | `source + source_job_id` | 同一来源重复跑不重复写 |
| 公司级 | `company_id`（全称/简称/别名归一） | 公司库、分组、ATS 映射；**不合并岗位** |
| 岗位级 | `company_id + 二级单位 + 岗位名 + 城市 + 届别` | 跨源同一岗位合并 |

**“按公司名去重”只做公司级。** 若拿公司名直接做岗位键，中铝一家的几百个岗位会被合成一条。岗位级还要看岗位名、城市、届别；标题变体/跨源重复用标题相似度 + JD 相似度模糊匹配，不确定的进复核，不静默删除。

每次运行：

- 已存在岗位只更新 `last_seen`，不新增行；
- 重复运行新增应为 0；
- 抓取失败不会把岗位标 `closed`；只有截止日期过期才自动 `closed`；
- 跨源合并保留全部来源链接，主链接按来源优先级选。

## 2027 届校招正式岗筛选

详见 `references/field-schema.md`。判定顺序：

1. 实习岗 / 社招 → 不推荐（配置可放开）；
2. 届别 < 2027 → 不推荐；
3. 学历要求大专/博士 → 不推荐；本科 → 标“需确认”，不直接排除；
4. 一线操作岗 → 不推荐；
5. 专业：平台字段 ∪ JD 正文命中白名单；字段写少很常见；
6. 城市：成都/南京优先，**不做硬过滤**；异地单独列出；
7. 届别/学历/专业/地点/校招属性任一不明 → **待核实**，不是可投；
8. 全部明确且通过 → **可投**。

日报会分别列「可投 / 待核实 / 异地 / 不推荐」，并给出排除统计，**不静默截断**。

## 输出

- SQLite：`~/.qiuzhao-radar/radar.db`
- 日报：`~/.qiuzhao-radar/reports/YYYY-MM-DD.md`
- CSV：`~/.qiuzhao-radar/export.csv`

日报结构：

```
今日新增 · 可投
今日新增 · 待核实
今日新增 · 异地高匹配
7 天内截止
宣讲会 / 招聘会
排除统计
数据源健康
数据说明与限制
```

## 定时运行

本机 `launchd`（macOS）或 `cron`，**不要用 GitHub Actions**：川e就/学校站点对海外 IP 不友好，后续如果需要企业 ATS 登录态也只能在本机。

示例（macOS，每天 08:30）：

```bash
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/com.qiuzhao.radar.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.qiuzhao.radar</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/weiqiao/Documents/personal-data-resources/01-睿睿的秋招/skills/qiuzhao-radar/scripts/radar.py</string>
    <string>collect</string>
    <string>--source</string><string>all</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>/tmp/qiuzhao-radar.log</string>
  <key>StandardErrorPath</key><string>/tmp/qiuzhao-radar.err</string>
</dict></plist>
PLIST
launchctl load ~/Library/LaunchAgents/com.qiuzhao.radar.plist
```

> 这台机器的 `python3` 是 `/usr/bin/python3` 还是 Homebrew 的，请按 `which python3` 调整。

## 飞书输出（已接入）

### 1. 公司级投递池

- Base：**简历投递记录**
- 链接：https://ncnmmj6cf0ef.feishu.cn/wiki/Ec98wjsfuifnEgk1gtbcbiWMn0c?table=tblPKAEr1fsJ3oSm&view=vewcGLAIyD
- 表：`投递记录`（`tblPKAEr1fsJ3oSm`）
- **一行一个公司**，不是一行一个岗位。
- 字段映射：
  - **岗位名称：不写**——这一列留到你投递后再填。
  - 公司 ← company_name
  - 公司类型 ← 自动归并（央国企/民企/外企/研究所/公务员/事业编/其他）
  - 城市 ← 该公司所有岗位城市的并集，多选：南京 / 成都 / 其他
  - 备注 ← 雷达发现 N 个岗位；可投/待核实/异地/不推荐数量；城市；来源；岗位ID；主要判定；截止
  - 投递状态 ← 待投
  - 岗位链接 ← 该公司最常用的招聘入口/ATS 链接
  - 截止日期 ← 该公司岗位中最早的截止日期
  - 优先级 ← 有可投→首选，否则有待核实→备选，否则→降级
- 去重：本地 `feishu_company_synced` + 表内已有「公司」名；已有公司不重复建行，也不覆盖你填的投递状态/备注。
- 公司下所有岗位都不推荐时不写入；有可投/待核实/异地任一才写。
- 当前表没有「二级单位 / 下一步」列，这两项写在备注里。
- 目前表里 31 条：30 条你的投递记录 + 1 条宁德时代公司行（岗位名称留空）。

### 2. 日报

- 飞书不再单独建日报文档（原 docx 已删除）；岗位数据全部进「投递记录」表。
- 本地仍生成 `~/.qiuzhao-radar/reports/YYYY-MM-DD.md`，包含可投/待核实/异地、宣讲会、投递进度和排除统计。
- 如果你想要一份飞书日报 docx，我可以重新创建并把 token 填回配置。

### 写入开关

`config.feishu.enabled` 控制是否写飞书；你的 `~/.qiuzhao-radar/config.json` 已打开并填好 token。`config.example.json` 里是空占位，方便换 Base。

## 审核清单

首次使用请重点检查：

- [ ] `data/chengdu_schools.json` 是否包含你要盯的学校；`scbdc_id` 是否正确。
- [ ] `config` 的 `target_cities`、`majors`、`keywords` 是否符合你的方向。
- [ ] 跑一次 `collect --keywords 2027届 --pages 1`，看“可投/待核实”的判定是否符合预期。
- [ ] 看 `references/dedupe.md` 的测试用例，确认公司名/岗位名/城市的合并边界。
- [ ] 是否要把科研院所、实习、社招打开。
- [ ] 飞书「投递记录」的公司级字段是否要再增删；是否允许 skill 更新已有公司行的备注/截止日期。
- [ ] 60 家 ATS 候选公司是否要删减；未映射 ATS 的公司可以后续用 `ats-discover` 补。

## 已知限制

- 川e就的职位搜索是全平台，不保证都是 2027 届校招；没有明确届别的会进「待核实」。
- 川e就的宣讲会/招聘会数据取决于各校上报，部分学校为空；日报只列未来日期的。
- 学校直连站多数有 WAF/登录态，未逐个实现；这是**有意为之**，避免维护 60 个脆弱爬虫。
- 平台不提供企业 ATS 的 `status=open`，所以不能用“平台在招”替代“官方核验”。
- 任何岗位在投递前都要打开链接确认；本 skill 不替你判断“最终能不能投”。
