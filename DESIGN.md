# bacmap Web 任务台设计系统（DESIGN.md）

> 适用范围：`src/bacmap/interfaces/web/`（任务列表 / 提交 / 详情 / 审批）。
> 硬约束：本地单机部署，**零外联**（ADR-16）——无 CDN、无 webfont、无外部图标包；
> FastAPI + Jinja2 服务端渲染 + 手写本地 CSS + 极少量原生 JS。
> 本文是唯一视觉决策来源：任何颜色 / 字号 / 间距 / 组件形态必须回溯到本文的 token；
> 需要 token 之外的东西时，先扩表，再使用。

## 0. 参考与审计（redesign-skill：先审计后动手）

### 0.1 路由决策（frontend skill）

- 定位：**运维仪表盘**（operational dashboard），用户是监控基因组分析任务的实验室科学家。
- Layer A：`taste-skill.md`（执行纪律：反 slop、状态完备、动效有义）。
- Layer B：`linear.app.md`（用户指定方向：modern quiet premium / Linear）。
  未换参考的理由：Linear 的暗色原生画布、亮度分层表面、单一靛蓝强调、510 字重体系
  正好匹配"长时间盯盘的本地运维台"的气质；Supabase/Stripe 更偏营销表面。
- 叠加：`layout-skill.md`（app-shell 滚动归属）、`perfection/README.md`（真浏览器 QA）、
  `designpowers lane-c`（客观证据优先于审美判断）。
- Design Read：本地病原菌基因组任务台，Linear 式暗色精密工程语言，
  CJK 系统字体栈，克制的有意义动效。

### 0.2 现状审计（改前基线）

| # | 问题 | 位置 | 处置 |
|---|------|------|------|
| A1 | 无 viewport meta，移动端必然溢出 | base.html | 补 `<meta name="viewport">` |
| A2 | 浏览器默认样式：无导航壳、无卡片层级、全边框表格 | 全部模板 | 建立 topbar + 卡片 + 语义表格 |
| A3 | 状态只是彩色文字，无徽章语义、running 无"活着"的反馈 | index/fragment | 状态徽章组件（点 + 中文标签 + 底色 tint），running 脉冲点 |
| A4 | 空状态是表格里一行"暂无任务"，无引导 | index | 组合式空状态（图标 + 文案 + 指向提交表单） |
| A5 | 无 hover/active/focus-visible 任何状态；无过渡 | 全部 | 补全三态 + focus ring |
| A6 | 详情页 2s 轮询直接 `innerHTML` 覆盖，**用户填写审批表单时每 2 秒被清空** | task_detail.html | 轮询前检测焦点/脏字段则跳过本轮；内容未变不写 DOM；终态停轮询 |
| A7 | 标题固定"bacmap 任务"，无 per-route title | base | `{% block title %}` |
| A8 | 内联 CSS 散在 head，无 token | base.html | 抽到 `/static/css/app.css`（token 化） |
| A9 | 图标缺失；无 favicon | 全部 | 内联 SVG（Lucide 路径）+ data-URI favicon |
| A10 | 键盘可达性：无 skip link、无 aria-live、无 aria-current | 全部 | 补齐 |

### 0.3 冻结方向（commit before tokens）

一句话：**"月光下的值班台"**——近黑画布上，信息靠亮度分层浮出；靛蓝只给"可以按下去的东西"，
状态语义各占一个克制的色相；任务 ID 与时间戳一律等宽字体，像仪器读数而不是网页文字。
访客会记住的一瞬间：运行中任务徽章上的呼吸点，和"待审批"卡上琥珀色的高级感。

Dials（taste-skill §1，操作台修订）：VARIANCE 4 / MOTION 3 / DENSITY 6。
主题锁：**仅暗色**（Light mode 记为已接受债务，见 §10）。

## 1. Atmosphere & Identity

安静的本地指挥台。近黑画布（#08090a）上没有一块纯色平板——表面靠亮度台阶
（#08090a → #0f1011 → #191a1b）与半透明白色发丝边框分层；阴影在暗面上不可见，
所以深度只来自亮度与 1px 边线。靛蓝 #5e6ad2 是唯一的品牌色，只出现在主按钮、
当前导航与焦点上；六个任务状态各有低饱和语义色相，以"点 + 中文标签"的徽章出现。
签名材质：**亮度分层 + 发丝边框 + 等宽读数**（ID/时间戳/tabular-nums）。

## 2. Color

### 2.1 基础盘（来源 linear.app.md §2，全部照抄其暗色体系）

| 角色 | Token | 值 | 用途 |
|------|-------|-----|------|
| 画布 | `--bg` | `#08090a` | 页面背景（最深） |
| 面板 | `--panel` | `#0f1011` | topbar、页脚条 |
| 浮面 | `--surface` | `#191a1b` | 卡片、表格容器 |
| 悬浮面 | `--surface-hover` | `rgba(255,255,255,0.04)` | 行/按钮 hover 叠加 |
| 内嵌面 | `--surface-inset` | `rgba(0,0,0,0.2)`（inset shadow） | 代码片、th 底 |
| 文本·主 | `--text-1` | `#f7f8f8` | 标题、正文（非纯白） |
| 文本·次 | `--text-2` | `#d0d6e0` | 输入值、表体 |
| 文本·三 | `--text-3` | `#8a8f98` | 辅助说明、占位、时间戳 |
| 文本·四 | `--text-4` | `#62666d` | 仅装饰性（禁用于正文，见 §9） |
| 强调 | `--accent` | `#5e6ad2` | 主按钮底、品牌点缀 |
| 强调·hover | `--accent-hover` | `#4f5ac4` | 主按钮 hover（**加深而非变亮**：白字对比 4.7→5.9:1） |
| 链接 | `--link` | `#828fff` | 链接文字（对 #08090a 对比 5.1:1） |
| 边线·标准 | `--border` | `rgba(255,255,255,0.08)` | 卡片、输入框 |
| 边线·弱 | `--border-subtle` | `rgba(255,255,255,0.05)` | 分隔线、topbar 底边 |
| 边线·强 | `--border-strong` | `#34343a` | 徽章描边等需要实体边处 |

规则：强调色只给可交互元素，永不作装饰；正文禁纯黑/纯白；一个页面一个灰系（冷灰）。

### 2.2 状态语义盘（六个 TaskState，低饱和冷调家族 + 琥珀审批）

徽章 = 色点 + 中文标签；底色为该色相 12% 透明度叠在 `--surface` 上，文字用亮 tint（对比均 ≥7:1）。
`state-*` 类名沿用现有契约（`state-running` 等）。

| 状态 | 类名 | 点/边 | 文字 | 底（rgba） | 中文标签 |
|------|------|-------|------|-----------|----------|
| pending | `--st-pending` | `#8a8f98` | `#a6adb8` | `rgba(138,143,152,0.12)` | 排队中 |
| running | `--st-running` | `#6aa1ff` | `#8ab5ff` | `rgba(106,161,255,0.12)` | 运行中 |
| awaiting_approval | `--st-await` | `#e8b64a` | `#eccf7a` | `rgba(232,182,74,0.12)` | 待审批 |
| succeeded | `--st-ok` | `#2fbe77` | `#5ad191` | `rgba(47,190,119,0.12)` | 已完成 |
| failed | `--st-fail` | `#e5484d` | `#ff8589` | `rgba(229,72,77,0.12)` | 已失败 |
| cancelled | `--st-cancel` | `#5c6167` | `#8a8f98` | `rgba(92,97,103,0.16)` | 已取消 |

色相语义就近分组的可辨性：失败红 / 待批琥珀 / 成功绿 / 运行蓝 / 中性灰两档——
色盲用户仍可靠"点 + 中文标签 + 位置"识别（颜色不是唯一编码）。

## 3. Typography

### 3.1 字体栈（零外联 → 系统栈，CJK 一等公民）

```css
--font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
  "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", "Source Han Sans SC",
  Roboto, sans-serif;
--font-mono: ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas,
  "Noto Sans Mono CJK SC", monospace;
```

### 3.2 字阶（px 依据 linear.app.md §3 压缩为操作台密度；CJK 行高放宽）

| 级别 | 字号/行高 | 字重 | 用途 |
|------|-----------|------|------|
| Display | 26px / 1.25 | 600 | 页标题（中文不需要巨标题） |
| H2 card | 15px / 1.4 | 600 | 卡片标题、区块题 |
| Body | 14px / 1.7 | 400 | 正文、表体（CJK 1.7 防挤压） |
| Body-lg | 15px / 1.6 | 400 | 表单 hint 之外的说明 |
| Label | 12.5px / 1.5 | 500 | 表单标签、表头（+0.02em） |
| Caption | 12px / 1.5 | 400 | 元信息、页脚 |
| Mono | 13px / 1.5 | 400 | 任务 ID、时间戳、state 原文（`tabular-nums`） |

### 3.3 CJK 排版规则

- **CJK 不用负字距**；Label 级小字加 `letter-spacing: 0.02em`。
- 中西文混排间隙交给字体栈（PingFang/YaHei 自带），不做手动 hair space。
- 长任务 ID 是无空格字符串：`overflow-wrap: anywhere` + 等宽，永不撑破容器。
- 正文不小于 14px；`<html>` 保持 `lang="zh"`。

## 4. Spacing & Layout

### 4.1 间距（4px 基）

`--sp-1:4 · --sp-2:8 · --sp-3:12 · --sp-4:16 · --sp-5:20 · --sp-6:24 · --sp-8:32 · --sp-10:40 · --sp-12:48`
卡片内边距 `--sp-6`；表单字段纵向节奏 `--sp-4`；卡片间距 `--sp-5`；页头下 `--sp-8`。

### 4.2 布局

- 内容容器 `max-width: 1200px`，左右 `--sp-5`。
- **index 非对称双栏**：提交表单卡 360px 固定 + 任务表 1fr（`grid-template-columns: 360px minmax(0,1fr)`）；
  `<1000px` 折为单列（表单在上，表格全宽）。
- **滚动归属**（layout-skill）：文档流滚动（本应用页面短，不做固定壳）；topbar `position: sticky`。
- 断点：`1000px`（index 折叠）、`640px`（表格纵排、topbar 收缩）。命名用 `--bp-*` 语义。

### 4.3 圆角 / 阴影 / 层级

- 圆角：控件/按钮/输入 `--r-ctl: 6px`；卡片 `--r-card: 8px`；徽章 `9999px`。全局就这三级。
- 深度策略（§7 详）：**borders-only + 亮度台阶**，暗面不用投影。

## 5. Components（先于实现定义；状态完备性在此声明）

### 5.1 Topbar（导航壳）
- 结构：`header.topbar > div.topbar__inner [ a.brand(svg 标志+wordmark+本地徽标) , nav.topnav(aria-current), .topbar__meta(数据不出网盾牌徽标) ]`
- 状态：链接 hover 文字 `--text-3 → --text-1`；当前页 `aria-current="page"` + `--text-1`；focus-visible ring。
- 滚动：sticky，底边 `--border-subtle`，背景 `--panel`。

### 5.2 Card
- 结构：`section.card`（`--surface` 底、`--border` 1px、`--r-card`、内边距 `--sp-6`）
- 变体：`.card--form`（表单卡）、`.card--table`（表格卡，内边距 0 + 表格满宽）、`.status-card`、`.approval-card`（琥珀顶线 2px 点题）
- 头部：`.card__head`（标题 + 右侧 count/徽章，space-between）。

### 5.3 Badge（状态徽章）
- 结构：`span.badge.badge--{state} > span.badge__dot + 文本`
- 形态：pill，Label 字级，点 6px；`--st-*` 三色组（点/文字/底 tint，§2.2）。
- 状态：running 的点做 2s opacity 脉冲（唯一循环动画，语义 = "活着"）；
  reduced-motion 下静止。
- ARIA：颜色非唯一编码——中文文本即语义；原始英文 state 以 `code.mono` 在详情页并列展示。

### 5.4 Button
- 变体：`.btn--primary`（`--accent` 底白字，hover `--accent-hover` 加深）、`.btn--ghost`（`rgba(255,255,255,0.02)` 底 + `--border` 边）
- 状态：hover（背景位移）、active `translateY(1px)`（物理按压）、focus-visible ring、disabled `opacity:.5 + cursor:not-allowed`。
- 尺寸：高 36px，Label 字级，圆角 `--r-ctl`。图标 + 文字时图标 16px、间距 `--sp-2`。

### 5.5 Field（表单字段）
- 结构：`div.field > label.field__label[for] + control + p.field__hint`；**标签永远在输入框上方**（不用 placeholder 当标签）。
- 控件：`.field__control`（`--surface` 上再叠 `rgba(255,255,255,0.02)`，`--border` 边，focus 边变 `--link` + ring）；
  可选字段标注 `.field__optional`（`--text-3` 小字）。
- 状态：hover 边亮一档；focus ring（3:1）；`::placeholder` 用 `--text-3`。
- 约束：hint 在下方，`--text-3`，12.5px。

### 5.6 TaskTable（语义表格）
- 结构：`table.tasktable > thead(视觉弱化 Label 级, --text-3, 下边线) + tbody tr(下边线 --border-subtle)`
- 状态：行 hover `--surface-hover`；ID 列等宽链接（hover 加亮 + 下划线）；时间戳 mono `--text-3`。
- 响应式：`<640px` 收起 thead，行变卡（`td::before content: attr(data-label)` 两端对齐）。
- 可达性：`th[scope=col]`；行首 ID 链接是唯一导航目标（整行不做点击区，避免键盘陷阱）。

### 5.7 EmptyState（空状态）
- 结构：`.empty > svg(40px inbox) + h3 + p + a(指向表单锚点)`；居中，`--sp-12` 上下留白。
- 文案真实、不用感叹号（"暂无任务 / 从左侧提交第一个分析任务"——移动端单列时指向顶部表单）。

### 5.8 Crumbs（返回路径）
- `nav.crumbs(aria-label="面包屑") > a(arrow-left 图标 + 任务列表) + sep + span.mono(当前 ID 截断)`。

### 5.9 StatusList（运行状态读数）
- `dl.statuslist > .statuslist__row(dt + dd)`；dt Label 级 `--text-3` 定宽 6em；dd `--text-2`；
  "消息/步骤"空值显示 `—`；整块活在 `#status[aria-live=polite]` 内，轮询换新时 240ms 淡入。

## 6. Motion & Interaction

| 类型 | 时长/缓动 | 用途 |
|------|-----------|------|
| Micro | 120ms ease-out | 按钮/链接/行 hover、active |
| State swap | 240ms cubic-bezier(0.16,1,0.3,1) | 轮询内容变化后的淡入上移 4px |
| Pulse | 2s ease-in-out 无限循环 | running 徽章点 opacity 1→0.35→1（唯一循环动画） |

规则：只动 `transform` / `opacity`；动效必须有义（反馈状态变化/活体信号），
禁止装饰性循环动画；`@media (prefers-reduced-motion: reduce)` 下全部动画/过渡归零
（脉冲点静止、淡入改为直接呈现）。

## 7. Depth & Surface

策略：**borders-only + 亮度台阶**（Linear §6：暗面投影不可见，深度 = 背景亮度分级 + 半透明白边）。

| 层 | 处理 | 用途 |
|----|------|------|
| L0 | `--bg` 无边 | 画布 |
| L1 | `--panel` + 底边 `--border-subtle` | topbar |
| L2 | `--surface` + `1px --border` | 卡片、表格容器 |
| L2.5 | `--surface` + `--surface-hover` 叠加 | 表格行/条目 hover |
| Inset | `inset 0 0 0 1px rgba(0,0,0,.2)` 或底纹 `rgba(255,255,255,0.02)` | 表头、code 片 |
| Ring | `0 0 0 3px rgba(130,143,255,0.35)` | focus-visible |

氛围：画布顶部一层极淡靛蓝径向光（`radial-gradient 60% at 50% 0%, rgba(94,106,210,0.10), transparent`），
为"月光指挥台"提供唯一的环境光；不随滚动移动，不叠加噪点（密度 6 的操作台不需要纹理）。

## 8. Responsive（375 / 768 / 1280 实测口径）

- **1280**：双栏 index（360px + 1fr），表格全列。
- **768**：折单列（表单在上、任务表全宽——5 列表格在半宽栏里必然挤压，单列更可读），
  topbar 保留品牌 + 数据不出网徽标。
- **375**：全部单列；表格纵排为"行卡"（thead 隐藏、`data-label` 前缀）；topbar 收缩
  （`<640px` 隐藏 `.brand__tag` 装饰标）；徽章不换行（唯一 `white-space: nowrap` 处）。
- 所有断点：主内容无横向滚动；长 ID/JSON 由 `overflow-wrap: anywhere` 兜底。

## 9. Accessibility Constraints

- WCAG 2.1 AA：正文对比 ≥4.5:1（本文所有文本 token 已按此校验；`--text-4 #62666d` 对 #08090a 仅 3.4:1，
  **只允许**用于装饰性字符，如面包屑分隔符）。
- 键盘：skip link（跳 `#main`）；所有可交互元素可见 focus-visible ring（§7 Ring token）；
  tab 顺序 = DOM 顺序。
- 表单：label 显式 `for`；必填用 HTML `required`；hint 关联默认可见（不依赖 hover）。
- 动态区：`#status` `aria-live="polite"`——配合"内容未变不写 DOM"，SR 只在真实变化时播报。
- 颜色非唯一编码：状态徽章始终有中文文本；running 脉冲是增强而非唯一信号。
- 触达：按钮高 36px；`<meta name="viewport">` 保证移动缩放正常。

## 10. Accepted Debt（登记即接受，不静默）

| 项 | 位置 | 为何接受 | 出口 |
|----|------|----------|------|
| 仅暗色主题（无 light mode） | 全站 | 用户指定 Linear 暗色原生方向；单工作站值班/监控场景长时盯暗面更省眼；本地工具无品牌双主题诉求 | 若实验室断要求亮色，按 §2 加 light token 表 + `prefers-color-scheme` 切换 |
| 状态中文标签映射在 `_badges.html` 宏内维护 | templates/_badges.html | Jinja 环境不可改（app.py 仅允许加 static mount），宏是唯一事实源 | 后端若开放 env.globals 再上移 |
| 详情页轮询间隔固定 2s，不可配置 | task_detail.html JS | 保持既有轮询契约，最小 JS | 需求出现时加 `data-interval` |
| 无 Lighthouse 自动化门（本地内网工具） | QA 流程 | 用真浏览器 Playwright 断点 + 状态遍历替代； perfection 的构建/包体杠杆在本栈（无构建链）不适用 | 若页面数量增长再引入 |
| Linear 的 Inter cv01/ss03 等宽特性不可用（零外联禁 webfont） | §3 | 用系统栈 + 等宽读数 + 字重 400/500/600 三档近似其 400/510/590 体系 | 若未来允许自托管字体再换 |

## 11. 本地性合规（ADR-16 映射）

- CSS/JS/图标/favicon 全部本地：`/static`（FastAPI StaticFiles）+ data-URI；页面发起的网络请求只有
  本站 `/tasks/*/fragment` 轮询。无 CDN、无字体下载、无分析脚本、无图片外链。
- 图标为 Lucide（ISC）路径数据的内联 SVG，`stroke="currentColor"`，线宽统一 1.5。
