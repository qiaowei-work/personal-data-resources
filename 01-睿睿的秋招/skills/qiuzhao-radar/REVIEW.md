# qiuzhao-radar 审核说明

## 1. 这次做了什么

新建 skill：`skills/qiuzhao-radar/`。

核心流程：

```
川e就（成都高校：职位 + 公告 + 宣讲会 + 招聘会）
四川农业大学（直连 JSON API）
NCSS（全国校招）
国聘（央企公开推荐池）
企业官方 ATS（北森 / Moka / 飞书）
        ↓
归一化（城市/学历/专业/届别/岗位类型/公告识别）
        ↓
脚本去重（来源级 / 公司级 / 岗位级 + 模糊匹配）
        ↓
2027 届校招正式岗初筛
        ↓
SQLite（~/.qiuzhao-radar/radar.db）
        ↓
飞书「投递记录」（一行一个公司；岗位明细进备注）→ 本地 Markdown/CSV
```

## 2. 已验证

- `python3 -m unittest discover -s tests -v`：**18 项全部通过**。
- 川e就真实抓取：关键词 `2027届`、`校园招聘`、`化工`，第一次 30 条原始岗位（去重后 28 条）、108 条学校事件；第二次 **新增 0**、30 条合并去重。
- NCSS 真实抓取：4 类单位性质各 1 页，60 条原始岗位；主题预过滤后入库 11 条。
- 国聘真实抓取：公开推荐池 1 页，9-12 条；主题预过滤后入库 2-4 条。
- 多源联合跑通（川e就 + 川农 + NCSS + 国聘）；川e就/NCSS 第二次 0 新增，国聘推荐池本身会变动，可能有少量新增，这是源的问题不是去重失效。
- 川农大直连：一次抓取 52 条宣讲会/招聘会事件。
- ATS 真实抓取：宁德时代 Moka 30 条、药明康德北森 100 条。
- 飞书：「投递记录」表按公司聚合，宁德时代只占 1 条公司行（总 31 条），**岗位名称列留空**；城市字段已改为多选；日报只保留本地 Markdown。
- 日报能正常生成；示例报告：`examples/sample-report.md`。
- 去重覆盖：跨源合并、同公司不同城市、同公司不同岗位、空城市、重复跑 0 新增。
- 筛选覆盖：2026 届、实习、大专、一线操作、银行/物业/销售等非目标岗位、招聘公告、异地、专业不限。

## 3. 当前真实覆盖

### 已实现

| 源 | 实现 |
|-|-|
| 川e就 | 职位搜索 + 学校公告/宣讲会/招聘会；按 `universityid` 覆盖成都高校 |
| 川农大 | 直连公开 JSON API（宣讲会 + 招聘会） |
| NCSS | 国家大学生就业服务平台公开匿名接口；按单位性质抓取 + 主题预过滤 |
| 国聘 | 公开推荐池接口；抓校园招聘/实习，跳过社招 |
| ATS | 北森 / Moka / 飞书招聘；60 家候选清单，已映射 4 家 |
| 成都高校清单 | `data/chengdu_schools.json`：62 所普通高校/职业院校 + 13 所在蓉科研院所（默认停用） |
| 去重 | `scripts/dedupe.py` + `scripts/store.py` |
| 日报 | `scripts/report.py`，含「投递进度」 |
| 飞书投递记录 | `scripts/feishu.py`，按公司聚合写入「投递记录」表；一行一个公司；不写岗位名称 |
| 日报 | 本地 Markdown；飞书只写投递记录表（日报 docx 已删除，不再更新） |

### 没实现（有意为之）

- 川大、电子科大、西南交大、成都大学等**直连站**：有 WAF / 登录态 / 反爬，当前统一走川e就。`data/chengdu_schools.json` 里保留了 `direct_url` 和 `note`，后续可按需补。
- **hotjob** 平台（万华化学 `whchem.hotjob.cn`、伊利 `yili.hotjob.cn`）：已识别，适配器待补。
- 60 家 ATS 候选里，目前只映射了宁德时代（Moka）、药明康德（北森）、万华/伊利（hotjob，待适配）；其余 56 家待逐家识别。
- 成都本地人社/国资委、高校人才网、公众号/手动链接：未接。
- BOSS/智联/51job：登录页已用 ego-browser 打开，抓取适配等登录后按真实页面补；暂不进入每日自动流。

## 4. 已知限制（审核时请重点看）

1. **川e就是“学校上报的聚合”，不是企业 ATS。** 日报里的 `platform_verified` 只代表“平台在招”，投递前仍要打开链接确认。
2. **“可投”非常保守。** 平台职位经常不写届别/专业/校招属性，这类进「待核实」；示例里 28 条唯一岗位只有 1 条「可投」。这是有意避免误报，但如果你觉得太严，可以放宽 `normalize.py` 的 `unknown_reasons`。
3. **招聘公告不是岗位。** 标题是“XX 2027届校园招聘/招聘简章”的，进「待核实」，不直接算可投；银行/物业/销售等公司/标题会直接不推荐。
4. **学校事件覆盖取决于各校上报。** 川大/电子科大的 `/campus`、`/teachin` 在川e就上可能为空，这是平台数据问题，不是抓取失败。
5. **岗位搜索是全平台的。** 关键词 `2027届` 最有效；只搜 `化工` 会混入大量社招/非校招岗位，这些会进「待核实」或「不推荐」。
6. **公司名去重只做公司级。** 岗位级还要看岗位名、城市、届别；这是刻意避免把中铝几百个岗位合成一条。
7. **飞书 Base 字段名必须和 `references/field-schema.md` 对齐。** `lark-cli` 只写已有字段，不负责建表。
8. **NCSS/国聘是宽口径池子。** 已用 `topic_keywords` 和 `strong_topic_keywords` 预过滤，但仍会有相邻方向（施工、设备、EHS）混进来；过滤数在日报「数据源健康」里可见。
9. **国聘推荐池会变动。** 同一页两次抓取可能拿到不同条目，导致少量“新增”；这不是去重失效。
10. **公司级表：** 同一公司多个岗位只占一行；目前“已有公司行”不自动更新备注/截止日期，避免覆盖你手填的投递状态和备注。新岗位仍会进本地日报。需要自动更新公司行摘要的话，我再加一个不覆盖人工字段的更新策略。

## 5. 审核清单

### A. 学校清单

打开 `data/chengdu_schools.json`，检查：

- 是否漏了你关心的学校；
- `scbdc_id` 是否正确（可跑 `python3 scripts/radar.py schools --refresh` 对照川e就下拉框）；
- 科研院所是否要开启（当前 `enabled: false`）；
- 成都/非成都校区的备注是否准确（川农、川财天府、四川工商等）。

### B. 筛选口径

打开 `scripts/normalize.py`，重点看：

- `DEFAULT_CONFIG["majors"]`：专业白名单是否要增减；
- `TARGET_PATTERNS` / `STRONG_NON_TARGET_PATTERNS` / `WEAK_NON_TARGET_PATTERNS`：岗位方向判定；
- `unknown_reasons`：哪些情况进「待核实」；
- `include_internships` / `include_social`：是否要放开实习/社招。

### C. 去重

打开 `references/dedupe.md` 和 `tests/test_dedupe.py`：

- 公司别名是否要补（`data/company_aliases.json`）；
- 模糊合并阈值是否合适（当前标题 0.96 / 0.90+JD 0.65）；
- “不确定进复核”是否符合你的预期。

### D. 飞书输出（已接）

| 输出 | 位置 |
|-|-|
| 岗位 + 投递记录 | 简历投递记录 / `投递记录`（`tblPKAEr1fsJ3oSm`）<br>https://ncnmmj6cf0ef.feishu.cn/wiki/Ec98wjsfuifnEgk1gtbcbiWMn0c?table=tblPKAEr1fsJ3oSm&view=vewcGLAIyD |
| 日报 | 本地 `~/.qiuzhao-radar/reports/`；飞书不单独建日报 |

- 所有岗位按公司聚合后写「投递记录」：一行一个公司，不再一行一个岗位。
- **岗位名称不写**：这一列留到投递后再填；雷达写入时置空。
- 城市字段已改为多选：南京 / 成都 / 其他；公司行取所有岗位城市并集。
- 去重：本地 `feishu_company_synced` + 表内已有公司名；已有公司不重复建行，也不覆盖你的投递状态/备注。
- 备注里写：发现岗位数、可投/待核实/异地/不推荐数量、城市、来源、岗位ID、主要判定、截止日期。
- 当前表没有「二级单位 / 下一步」列，这两项写进备注。
- 本地 `~/.qiuzhao-radar/reports/` 留日报；飞书不单独建日报。

## 6. 怎么跑

```bash
cd "/Users/weiqiao/Documents/personal-data-resources/01-睿睿的秋招/skills/qiuzhao-radar"

# 1. 单元测试
python3 -m unittest discover -s tests -v

# 2. 初始化配置（写到 ~/.qiuzhao-radar/config.json）
python3 scripts/radar.py init

# 3. 最小验证：只看 2027 届岗位，不抓学校事件
python3 scripts/radar.py collect --source scbdc --keywords 2027届 --pages 1 --days 60 --no-events

# 4. 单独验证 ATS
python3 scripts/radar.py collect --source ats --ats-company 宁德时代 --pages 1 --no-events

# 5. 看日报 + 写飞书
python3 scripts/radar.py report

# 6. 登录 BOSS/智联/51job（ego-browser，会停在登录页）
python3 scripts/radar.py login

# 7. 正式日常：全部源 + 学校事件
python3 scripts/radar.py collect --source all --pages 3 --days 30
```

## 7. 需要你拍板

1. **60 家 ATS 候选**：要删减哪些？未映射的 56 家我按 `ats-discover` 逐家补，还是先只盯已映射的宁德时代/药明康德/万华/伊利？
2. **登录平台**：BOSS/智联/51job 登录后，第一批抓取范围（关键词、城市、页数）是什么？
3. **hotjob**：万华/伊利用的 hotjob 平台，要不要优先适配？
4. **飞书**：公司级「投递记录」的字段/备注是否要调整？已有公司行是否允许 skill 更新备注和截止日期？
5. **“可投”口径**：现在很保守，是否接受？
