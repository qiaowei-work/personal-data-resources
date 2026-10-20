# 信息源与成都高校清单

## 1. 当前源矩阵

| 层级 | 源 | 当前实现 | 可信度标记 | 说明 |
|-|-|-|-|-|
| 省级高校聚合 | 川e就—四川大学生就业服务平台 | `scripts/scbdc.py` | `platform_verified` | 四川省教育厅平台；岗位、学校公告、宣讲会、招聘会 |
| 学校直连 | 四川农业大学就业信息网 | `scripts/sicau.py` | `school_verified` | 公开 JSON API，无需登录 |
| 学校直连 | 川大/电子科大/西南交大/成都大学等 | 未实现 | — | 有 WAF/登录态/反爬，当前走川e就 |
| 国家平台 | 国家大学生就业服务平台 NCSS | `scripts/ncss.py` | `platform_verified` | 公开匿名接口；按单位性质抓取，主题预过滤 |
| 央企聚合 | 国聘网 | `scripts/iguopin.py` | `platform_verified` | 公开推荐池约 400 条；完整搜索需登录态 |
| 企业官方 ATS | 北森/Moka/飞书 | `scripts/ats.py` | `employer_verified` | 已接三类；60 家候选里已映射 4 家；hotjob 待适配 |
| 商业平台 | BOSS/智联/51job | 未接入 | `unverified` | 登录态 + 反爬 + 条款风险；只在需要时人工/ego-browser 补漏，不做每日自动 |

> 当前 MVP 的目标是**先把学校源 + 两个官方聚合源跑稳**，不是一口气接完所有企业 ATS。

## 2. 川e就平台

- 入口：`https://bigdata.scbdc.edu.cn:8888/`
- 页面：
  - `/job/search`：平台职位（列表自带 JD 摘要、薪资、地点、学历、专业、人数）
  - `/campus`：学校招聘公告
  - `/teachin`：学校宣讲会
  - `/jobfair`：学校招聘会/双选会
- 学校筛选：这些页面的 `universityid` 来自 224 个学校/院所下拉框。
- 列表是 **base64 + zlib + 两次 substr** 压缩后内嵌的，`scripts/scbdc.py` 的 `decode_page()` 已还原。
- 注意事项：
  - `/job/search` 是全平台职位，不保证都是 2027 届校招；届别/校招属性要靠标题或 JD 判断，判断不了进“待核实”。
  - 岗位列表的申请按钮需要登录；本 skill 只读取列表和详情链接，不登录。
  - 页面可能对海外 IP 或高频请求不友好；本 skill 固定低频、串行请求。
  - 学校公告/宣讲会数据取决于各校是否上报，部分学校为空是正常现象。

## 3. 国家大学生就业服务平台（NCSS）

- 入口：`https://www.ncss.cn/`
- 接口：`https://www.ncss.cn/student/jobs/jobslist/ajax/`
- 方式：GET，参数 `property`（单位性质）、`offset`（页码，从 1 开始）、`limit=20`。
- 当前默认单位性质：
  - 国有企业
  - 机关/事业单位/非营利机构
  - 民营企业
  - 外商投资企业
- 限制：匿名接口每个查询最多返回约 100 条；无截止时间字段，通常也没有完整 JD；专业字段经常为空。
- 处理：先按 `topic_keywords` / `strong_topic_keywords` 预过滤，再走统一门槛；届别/专业不明的进「待核实」。
- 已实测字段：`jobName / recName / areaCodeName / degreeName / major / headCount / lowMonthPay / highMonthPay / publishDate / jobId / recProperty`。

## 4. 国聘网

- 入口：`https://www.iguopin.com/job/list`
- 当前接口：`https://gp-api.iguopin.com/api/jobs/v1/recom-job`（公开推荐池，约 400 条）。
- 请求：POST JSON，`search.page/page_size` + `recom`；需要 `Referer: https://www.iguopin.com/job/list`。
- 当前只取「校园招聘/实习」，跳过「社会招聘」；可按 `iguopin.campus_only` 配置。
- 字段较全：`job_name / company_name / department_cn / education_cn / amount / major_cn / district_list / start_time / end_time / contents / recruitment_type_cn / company_info.nature_cn`。
- 限制：推荐池只有约 400 条；完整的 `/api/jobs/v3/list` 搜索需要登录态/签名，当前不接。需要全量时用已登录的 ego-browser 做关键词搜索。

## 5. 企业官方 ATS

- **北森**：`{slug}.zhiye.com`，POST `/api/Jobad/GetJobAdPageList`，`BusinessType=2` 取校招；已被药明康德等使用。
- **Moka**：`app.mokahr.com/campus-recruitment/{orgId}/{siteId}`，POST `/api/outer/ats-apply/website/jobs/v2`；响应 `data` 是 base64，用 `necromancer` 作为 AES key、固定 IV 解密。已实测宁德时代（`catlhr/148948`）。
- **飞书招聘**：`{host}.jobs.feishu.cn`，POST `/api/v1/search/job/posts`；需要门户 `website-path`，从首页 `js-websiteInfo` 读取。已用理想汽车门户验证。
- **hotjob**：`{slug}.hotjob.cn`，万华/伊利等在用；先识别，适配器待补。
- 公司映射：`data/target_companies.json`；用 `python3 scripts/radar.py ats-discover --url <招聘门户URL> --company <公司名>` 识别并写回。
- ATS 是**核验层**：平台/学校说“在招”，ATS 才能给出企业官方岗位、截止时间、完整 JD。只读公开岗位，不登录、不投递。

## 6. 成都高校清单

`data/chengdu_schools.json` 包含 60+ 条：

- **本科/职业本科**：四川大学、电子科技大学、西南交通大学、西南财经大学、西南民族大学、四川农业大学（成都校区）、西南石油大学、成都理工大学、成都中医药大学、四川师范大学、成都信息工程大学、四川音乐学院、成都体育学院、成都医学院、成都大学、成都师范学院、成都工业学院、四川旅游学院、成都东软学院、成都文理学院、成都锦城学院、成都银杏酒店管理学院、电子科技大学成都学院、四川工商学院、成都外国语学院、吉利学院、四川传媒学院、四川电影电视学院、西南交通大学希望学院、西南财经大学天府学院、成都艺术职业大学、成都航空职业技术大学、成都轻工职业技术大学等。
- **高职/专科**：四川电力职业技术学院、四川交通职业技术大学、四川邮电职业技术学院、四川航天职业技术学院、四川水利职业技术学院、四川国际标榜职业学院、四川商务职业学院、四川艺术职业学院、四川科技职业学院、四川文化产业职业学院、四川财经职业学院、四川城市职业学院、四川现代职业学院、四川长江职业学院、四川托普信息技术职业学院、四川华新现代职业学院、四川铁道职业学院、四川文化传媒职业学院、四川护理职业学院、四川文轩职业学院、四川西南航空职业学院、四川体育职业学院、成都职业技术学院、成都农业科技职业学院、成都工业职业技术学院、成都工贸职业技术学院、成都轨道交通职业学院、四川工商职业技术学院等。
- **在蓉科研院所（默认停用）**：中科院成都有机化学所、成都生物所、光电所、成都计算机应用所、山地所、中国核动力研究设计院、核工业西南物理研究院、611所、624所、西南技术物理所、西南自动化所、电信五所、西南通信所。

> **“所有学校”的口径**：以川e就 224 个学校/院所选项里能对应到成都的为准，加上已知在蓉高校。中职/技校、非成都校区不在默认清单；需要时在 JSON 里加 `enabled: true` 和对应 `scbdc_id`。

### 直连站状态（为什么不逐个爬）

| 学校 | 直连入口 | 状态 | 处理 |
|-|-|-|-|
| 四川大学 | `jy.scu.edu.cn/eweb/jygl/index.so` | WAF 483 | 走川e就 2009 |
| 电子科技大学 | `jiuye.uestc.edu.cn/career/` | Nuxt API 需登录 | 走川e就 2011 |
| 西南交通大学 | `jiuye.swjtu.edu.cn/eweb/jygl/zpfw.so` | WAF | 走川e就 2010 |
| 成都大学 | `jy.cdu.edu.cn` | 接口反爬/JS 挑战 | 走川e就 3047 |
| 四川农业大学 | `job.sicau.edu.cn` | 公开 JSON API | 已直连 |
| 其他高校 | 见 JSON `direct_url` | 多数未验证 | 默认走川e就；有公开 API 再加适配器 |

**新增直连站的条件**：公开、无需登录、结构稳定、请求频率可控。不满足就继续走川e就，不写脆弱爬虫。

## 7. 新增学校

1. 运行 `python3 scripts/radar.py schools --refresh`，看川e就当前下拉框。
2. 在 `data/chengdu_schools.json` 加：
   ```json
   {"name": "学校名", "scbdc_id": "xxxx", "type": "university", "adapter": "scbdc", "direct_url": "", "enabled": true, "note": ""}
   ```
3. 没有 `scbdc_id` 的学校标 `adapter: "manual"`，不要猜 ID。
4. 直连站需要单独写 adapter 时，参照 `sicau.py` 的接口，输出统一的 event/job 字段。

## 8. 运行边界

- 只读公开页面；不登录、不绕验证码、不绕 WAF、不碰个人简历数据。
- 串行请求，同一站点间隔 ≥0.6 秒；每日一次。
- 抓取失败不删数据、不把岗位标 closed；日报显示源健康状态。
- 岗位是否在招，最终以链接打开后的官方页面为准；平台标记只是“平台在招”。

## 9. 后续可加的源（按优先级）

1. **hotjob / 大易 / 自建 ATS**：补万华、伊利等目标公司；自建站按公司逐个适配。
2. **成都本地人社/国资委**：地方国企、事业单位公告。
3. **高校人才网**：科研院所、高校教职/科研岗；当前科研院所默认停用，开启后可配合。
4. **公众号/手动链接**：企业官方招聘公众号、学校就业网、内推链接；用 `manual` 方式把 URL/截图交给 skill 解析。
5. **聚合站**：牛客校招日程、OfferStar、应届生求职网；只做线索，必须回官网核验。
6. **BOSS/智联/51job**：ego-browser 登录态；第一批登录页已打开，抓取适配待登录后接。
