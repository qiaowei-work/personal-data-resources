# 网申表单填报

第三步的执行手册。**红线：AI 只负责填，提交一律由本人点击。**

本文件只讲**跨站点通用**的东西。某个站点特有的结构、字段、选项，记到 `site-adapters.md`。

---

## 一、会话前置

1. 浏览器 MCP 可用（断连处理见 SKILL.md Step 0）
2. **用户已在浏览器里登录目标站点** —— 不代登录、不碰账号密码
3. **个人信息源已确认**（见 §4.1）
4. 明确本次填的是哪张表：
   - **简历档案**（站点个人中心，一次性建档，长期复用）
   - **岗位申请表**（投一个岗位填一次）

---

## 二、核心认知：页面几乎都是 React 受控组件

主流招聘站（国聘、北森、Moka、用友大易系）都是 React + antd。
**直接 `el.value = x` 会被 React 丢弃** —— 输入框视觉上有值，提交时是空的。

这一节是第三步最大的技术门槛。**不要试图用「看起来填上了」判断成功**（见 §5）。

### 2.1 文本类（input / textarea）—— 走原生 setter

```js
const proto = el.tagName === 'TEXTAREA'
  ? HTMLTextAreaElement.prototype
  : HTMLInputElement.prototype;
Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, val);
el.dispatchEvent(new Event('input', { bubbles: true }));
```

**必须用原型上的 setter，不能直接赋值。** 这是 React 追踪值变化的唯一途径。

### 2.2 可搜索下拉（学校 / 专业 / 学历 …）

三步顺序不能乱：

1. `mousedown` + `click` 打开 `.ant-select-selector`
2. 用 §2.1 的 setter 往 select 内部的 `input` 写关键词 → 触发**异步**搜索
3. 等 1.5s 左右，点 `.ant-select-item-option`

**直接写 `input.value` 会被重置为空**（实测：某站点「学校名称」连试两次，`value` 都回到 `""`）。
写完关键词不等待就找选项，会拿到上一次的搜索结果 —— **搜索框残留关键词是个高频陷阱**，
换关键词前先清空。

### 2.3 级联选择器 —— 点开的是弹窗，不是下拉

antd 的 cascader 在这些站点上常被实现成 **`ant-modal`**，结构：

```
.ant-modal
  .flat-left     ← 一级（省 / 行业门类 / 职位大类）
  .flat-right    ← 下级（市 / 区 / 子行业 / 细分职位）
  .label-path    ← 面包屑，用来确认当前层级
```

- 点**叶子**通常自动确认并关闭（省 → 市 → 区 走完即完成）
- **多选**的级联**不会自动关**，必须再点「确定」，且**常有数量上限**
  （实测：某站点「期望行业」上限 3 个，界面显示「已选：n/3」）
- `.flat-left` 内容多时会虚拟滚动，**不要按位置点，一律按文本精确匹配**
- 取文本时注意：面板里有 SVG 图标，`el.innerText` 为 `undefined`，
  遍历必须写 `(el.innerText || '')`，否则整个脚本抛错中断

### 2.4 文件上传（照片 / 简历附件）

**`chrome-devtools-mcp` 的 `upload_file` 在这类页面上不可用。**
实测：工具返回「uploaded successfully」，但**页面的 change 事件没触发**，
React 收不到，`input.files.length` 始终为 0 —— 连试三次都一样。

**可行做法**：起一个带 CORS 的本地静态服务，让页面自己把文件取回来。

```python
# 在目标文件所在目录起服务，务必带 CORS 头
import http.server, socketserver

DIR = "<存放照片/简历的目录>"

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=DIR, **k)
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

socketserver.TCPServer(("127.0.0.1", 8899), H).serve_forever()
```

页面上下文：

```js
const r = await fetch('http://127.0.0.1:8899/photo.jpg', { cache: 'no-store' });
const file = new File([await r.blob()], 'photo.jpg', { type: 'image/jpeg' });
const dt = new DataTransfer();
dt.items.add(file);
const inp = document.querySelector('input[type=file]');
inp.files = dt.files;
inp.dispatchEvent(new Event('input',  { bubbles: true }));
inp.dispatchEvent(new Event('change', { bubbles: true }));
```

https 页面 fetch `http://127.0.0.1` **不受混合内容拦截**（localhost 视为安全来源），已实测通过。

**附带两个坑：**

- MCP 的 `upload_file`、截图落盘、`take_snapshot` 落盘，**路径必须在会话工作区内**
  （`/tmp` 会被拒）。快照用 `filePath` 落到工作区再 grep —— 比直接读省 token（快照动辄 5 万字符，一次就能吃掉大半上下文）。
- 服务**用完立即停掉**，不要长期挂着。
- 上传前先压图。证件照原件常有 3~4 MB、3000+ px，压到长边 900 px 再传。

### 2.5 「保存」按钮必须用 CDP 真实点击

**实测：`button.click()` 在板块的「保存」按钮上不生效** —— 点了等于没点，表单仍是编辑态，
且**没有任何报错**。但弹窗内的「取消 / 确定」、级联叶子、单选按钮，`click()` 都能用。

**唯独板块的「保存」必须走真实点击：**

```
take_snapshot（filePath 落盘）→ grep "保 存" 拿 uid → mcp__chrome-devtools__click
```

**这条是最容易踩的坑**：先用 `click()` 点一次、看没报错就以为存了，继续往下做，
最后发现整个板块都没保存。

### 2.6 定位元素：用文档顺序，不要用坐标

**板块列表的 `getBoundingClientRect().top` 不可靠** —— 许多站点把各板块放在
固定高度的滚动容器里，坐标是相对该容器的，不同板块的坐标会重叠甚至为负。

按坐标挑「添加」按钮会**点错板块**（实测：想点「教育经历」的添加，点开了「工作/实习经历」）。

**可靠做法**：把 `h2` 和小节按钮按 `compareDocumentPosition` 排序，取目标 `h2` 之后最近的按钮。

```js
const nodes = [...document.querySelectorAll('h2, button')]
  .sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1);
const i = nodes.findIndex(n => n.tagName === 'H2' && n.innerText.includes('<板块名>'));
let btn = null;
for (let j = i + 1; j < nodes.length; j++) {
  if (nodes[j].tagName === 'BUTTON') { btn = nodes[j]; break; }
  if (nodes[j].tagName === 'H2') break;          // 到下一个板块就停，别越界
}
```

**另外两个定位陷阱：**

- **`id` 可能不唯一或与容器同名**。实测：某站点的 `#assessment` 是**外层 div**，
  真正的 textarea 是它的子元素 —— `querySelector('#assessment')` 拿到的是 div，
  用 textarea 的 setter 去写会报 `Illegal invocation`。**动手前先确认 `tagName`。**
- 多个板块各自有 `#period_start` / `#title` / `#duty` 这类同名 id（因为同一时刻只展开一个编辑器）。
  **一旦同时打开两个编辑器，`querySelector` 就会串**。开新板块前先确认旧板块已保存收起。

### 2.7 未保存就切板块会弹确认框

文案类似：「有内容没有保存，确定退出编辑吗？ / 退出编辑后，更新的内容不会自动保存」。

**这不是报错**，是在提示上一个板块还处于编辑态。先回去保存，再继续。
**把它当成一个信号**：看到它就说明有东西没存上。

---

## 三、字段陷阱（跨站点通用）

| 陷阱 | 说明 |
|-|-|
| **起止时间必须填结束时间** | 平台普遍没有「至今」选项，进行中的经历**无法如实表达**。只能填预计结束（如预计毕业时间）—— 这属于对未来的陈述，**必须向用户说明并确认** |
| **单选 / 多选要先探明** | 外观相似的分类下拉，有的单选有的多选。看 `.ant-select-single` / `.ant-select-multiple`，以及有没有「已选：n/m」。**单选意味着只能表达一个值**（如城市只能填一个），要提前告知用户 |
| **平台分类 ≠ 真实岗位名** | 平台的一级分类往往**没有**具体岗位名，只有粗粒度上位类目。只能取最接近的，**并向用户说明这不等价** |
| **选项枚举不覆盖现实** | 实测：单位性质没有「政府机关」、行业没有「在校学生」。遇到时必须停下来告诉用户，**不要硬塞一个近似的** —— 硬塞等于替用户做了虚假陈述 |
| 分类字段是多段选择 | 如学历 / 专业分类常是「培养层次 / 门类 / 专业类」三元组，要先选层次才能搜到专业 |
| 在读学位不要选「有学位证」 | 尚未取得的证书不要默认勾选 |
| 选填板块不要强行补 | 完成度标记里选填项不勾是正常的 |

---

## 四、填报纪律

### 4.1 一切取自飞书，不编造

**个人信息全部来自飞书个人信息库** —— 它是唯一的信息来源，不用户口述、不用旧简历、
不靠行业惯例。节点位置见 SKILL.md「输入」。

若该库里有一页是**按表单字段组织的对照页**（如「填表速查卡」），**优先用它**。

飞书里没有的字段：

1. 先查该库自带的「待补充清单」之类
2. 仍没有 → **停下来问本人**
3. **不得用行业惯例补**，哪怕看起来"标准答案很明显"

### 4.2 必填但拿不到数据时

有些字段必填，但用户也不一定立刻答得上来（典型：税前月薪、期望薪资）。

**取值原则：选不构成虚假陈述的最小值。**

- 薪资类：填 `0` 或平台提供的「保密 / 面议」选项
- 日期类：宁可留空，**不要编一个日期**
- 选项类：没有合适选项时**留空**，不要硬选

**无论怎么处理，都要在交付时单独列出请用户复核**（见 §4.3）。

### 4.3 每次判断都留痕

交付时逐条列出「我替你做的判断」：

- 哪些字段平台没有对应选项，取了最接近的哪个
- 哪些字段是单选，只能表达一个值
- 哪些必填字段缺数据，用了什么值
- 哪些板块因选项不匹配而未填，以及替代方案

**Why:** 网申提交后改不了，用户必须能逐条复核。
只报「填完了」等于让用户盲信 —— 这和硬规则第 3 条（输出可复核）是同一条原则。

### 4.4 按板块推进，填一个保存一个

不要攒着最后一起保存 —— 出错后定位成本高，而且**见 §2.5，保存可能静默失败**。

---

## 五、验证（填完必做）

1. **单板块**：保存后确认
   - 编辑器已关闭（页面上找不到「保存」按钮）
   - `.ant-form-item-explain-error` 为空
2. **整体**：`navigate_page` **reload**，回读每个板块的渲染结果
3. **完成度标记**：多数站点有「简历目录」之类的侧栏，逐项核对打勾状态
4. **截图目视**：关键字段（照片、日期、分类）截图确认

**只信回读，不信「点了保存」。** 实测中保存过一次没生效，靠刷新才发现。

---

## 六、站点适配与沉淀

站点特有的结构、接口、字段、选项陷阱 —— 记到 `site-adapters.md`。

**每适配一个新站点，就把这次的发现补录进去。** 特别值得记的：

- 表单是单页还是分组弹窗、板块如何展开
- 哪些字段是级联弹窗 / 可搜索下拉 / 单选多选
- 该站点特有的必填项和选项缺口
- 保存机制（是否有独立「保存」、是否自动保存）

---

## 七、待实测

- **岗位申请表**（非简历中心）：各站点投递表单的字段与交互尚未实测
- 简历 PDF 上传到网申表单的流程
- 保存后二次编辑、覆盖的行为
- 是否有站点支持「至今」（目前实测的都不支持）
