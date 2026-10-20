# 去重设计（脚本实现）

## 1. 为什么不能只用公司名

公司名是**公司级**键，不是**岗位级**键。

实测背景：中铝 2027 校招有 559 个岗位，光叫“工程技术”的就有 8 个，还分属不同二级单位。如果按公司名去重，这家公司的所有岗位会合成一条，用户会漏掉绝大多数机会。

所以拆成三层：

| 层 | Key | 解决什么 | 不做什么 |
|-|-|-|-|
| 来源级 | `source + source_job_id` | 同一来源每天跑不重复写 | — |
| 公司级 | `company_id`（规范名/别名） | 同名、简称、母公司重复；公司库、分组、ATS 映射 | **不合并岗位** |
| 岗位级 | `company_id + sub_company + title + city + grad_year` | 同一岗位出现在川e就/川农/其他学校 | 不把同公司不同岗位合并 |

## 2. 公司级归一化

`dedupe.normalize_company_name()`：

1. NFKC、去空格、去括号/标点；
2. 循环去掉法律后缀：`股份有限公司`、`有限责任公司`、`集团有限公司`、`有限公司`、`集团`、`公司`；
3. 查 `data/company_aliases.json` 别名表；
4. `company_id = sha1(canonical_name)[:12]`。

示例：

```
中国铝业集团有限公司 / 中国铝业股份有限公司 / 中铝 / Chinalco -> 中铝集团
万华化学集团股份有限公司 / 万华化学 -> 万华化学
宁德时代新能源科技股份有限公司 / CATL -> 宁德时代
```

**二级单位保留**：

```
中铝西南铝、中铝洛阳铜业、中铝郑州研究院 -> 不同 sub_company，不合并
```

## 3. 岗位级去重

### 精确键

```
company_id | sub_company_norm | title_norm | city | grad_year
```

`title_norm`：

- 去掉开头的 `【秋招】`、`（校招）`；
- 去掉 `2027届`、`校园招聘`、`秋招`、`春招`、`补录`、`急聘`；
- 去掉括号里的城市/地点；
- 去空格、标点、转小写。

示例：

```
2027届校园招聘-工艺工程师（成都） -> 工艺工程师
【秋招】工艺工程师                 -> 工艺工程师
工艺工程师（校招）                 -> 工艺工程师
```

### 模糊匹配（跨源标题不一致时）

只在同一个 `company_id + city` block 内比较：

```
标题相似度 >= 0.96 -> 合并
标题相似度 >= 0.90 且 JD 3-gram Jaccard >= 0.65 -> 合并
标题相似度 >= 0.90 且两边 JD 都为空 -> 合并并进复核
其余 -> 新岗位，必要时进 duplicate_reviews
```

**不确定就保留两条 + 进复核，不静默删除。**

### 来源优先级

```
企业官方 ATS (5) > 川e就/川农/学校官方 (4) > 聚合站 (2) > 手工 (1)
```

合并时：

- `first_seen` 保留最早；
- `last_seen` 更新为最近一次；
- 字段按来源优先级 + 完整性选值；
- 所有来源链接进 `job_sources`，主链接选最高优先级；
- 截止日期冲突：高优先级来源优先，低优先级值保留在来源记录里；
- 不删除历史，只改 `status`。

## 4. 频繁运行规则

| 规则 | 实现 |
|-|-|
| 幂等 | `jobs.job_key UNIQUE`，`job_sources(source, source_job_id) UNIQUE`；`ON CONFLICT` 更新 |
| 重复跑 0 新增 | 同一岗位只更新 `last_seen` |
| 条件请求 | 当前按每日一次 + 低频；后续可加 ETag/Last-Modified |
| 详情页只抓新 ID | 当前职位列表已带 JD 摘要，MVP 不抓详情；后续加详情时按新 ID 抓 |
| 失败不误杀 | 源失败不标 closed；只有截止日期过期自动 closed |
| 只报变化 | 日报只列 `first_seen = 今天` 的新增 + 7 天内截止 + 未来事件 |
| 防并发 | SQLite WAL + `busy_timeout`；定时任务不要重叠 |
| 全量校准 | 后续每周跑一次全量（`--days 0`）对账 |

## 5. SQLite 结构

```sql
companies(company_id PK, canonical_name, alias_json)
jobs(id PK, job_key UNIQUE, company_id, company_name, sub_company, title, title_norm,
     city, education, majors, grad_year, job_type, deadline, recommendation,
     reasons_json, source, source_type, source_job_id, url, apply_url,
     verification_status, first_seen, last_seen, status, sources_json)
job_sources(id PK, job_id, source, source_job_id, source_type, url,
            first_seen, last_seen, raw_json,
            UNIQUE(source, source_job_id))
events(id PK, event_key UNIQUE, source, source_event_id, event_type, school,
       title, company, organizer, event_date, deadline, location, url,
       first_seen, last_seen, raw_json)
runs(run_id PK, started_at, finished_at, stats_json)
duplicate_reviews(id PK, job_id_a, job_id_b, reason, decision, created_at)
```

## 6. 测试与验收

`tests/test_dedupe.py` 覆盖：

- 同一岗位从川e就 + 川农来 -> 1 条岗位、2 个来源；
- 同公司不同城市 -> 2 条；
- 同公司不同岗位 -> 2 条；
- 同一来源重复跑 -> 0 新增；
- 标题变体 -> 合并；
- 2026 届 / 实习 / 大专 / 一线操作 -> 不推荐；
- 异地 -> 异地；
- 专业不限 -> 可投。

命令：

```bash
python3 -m unittest discover -s tests -v
```

**验收标准**：

1. 同一岗位跨源抓两次，库里只有 1 条岗位、N 条来源；
2. 中铝总部和“中铝西南铝”不合并；
3. 同一公司不同城市/不同岗位不合并；
4. 连续跑两次，第二次 `新增 = 0`；
5. 某个源抓取失败，已有岗位不会被标 closed。
