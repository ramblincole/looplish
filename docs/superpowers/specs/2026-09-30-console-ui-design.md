# Looplish 控制台风格界面重做 设计说明

- 日期：2026-09-30
- 范围：`apps/web`（仅前端；后端接口与 OpenAPI 契约不变）
- 视觉参考：`C:\workspace\whisper-split\web`（`index.html`、`style.css`、`app.js`）

## 1. 背景与目标

Looplish 的前后端基础功能已经完成（Task 01–12），但界面只有最基本的排版，试用体验简陋。whisper-split 是 Looplish 重构前的版本，界面效果好，但代码是一个 600 行的全局脚本加一张全局样式表，不易维护。

本次重做的目标：

1. 视觉与交互对齐 whisper-split 的「语言实验室控制台」风格。
2. 代码组织达到工程级别：样式按组件隔离、设计变量集中、通用组件与业务组件分层、行为可测试且测试不依赖样式实现。
3. 顺带修复 PR #19 评审遗留的 4 条 Minor。

非目标：

- 不改后端、不改 API 契约。
- 不做浅色主题（只做暗色）。
- 本句进度条不支持点击跳转，只做展示。

## 2. 已确认的决策

| 问题 | 决定 |
|---|---|
| 视觉风格 | 照搬 whisper-split 暗色控制台风格，只有暗色主题 |
| 样式方案 | 每个组件一个 CSS Module；全局只保留设计变量与基础样式 |
| 样式检查 | 引入 stylelint，并入 `lint` |
| 新增交互 | 练习台读数条、本句进度条（只展示）、快捷键面板与 toast 操作提示、新建任务后的处理进度浮层 |
| 文件上传 | 保留 Task 11 的显式确认：选中或拖入后需点「上传并处理」 |
| 「与句子等长」留白 | 按实际听到的时长：`sentence.duration / rate` |
| 句子清单遮罩 | 与参考版一致：当前句处于遮罩状态时整列原文模糊；搜索命中项始终清晰 |
| 交付 | 拆成 3 个依次合并的 PR（见第 9 节） |

## 3. 样式架构

### 3.1 分层

| 层 | 文件 | 职责 |
|---|---|---|
| 设计变量 | `src/styles/tokens.css` | 唯一定义颜色、字体、圆角、间距、动效时长、层级的地方 |
| 基础样式 | `src/styles/base.css` | 盒模型、`html/body` 底色与顶部暖光、表单控件继承字体、`:focus-visible`、`[hidden]`、`prefers-reduced-motion`、`.visuallyHidden` 工具类 |
| 组件样式 | `*.module.css`，与组件同目录 | 组件自身布局与外观，只能引用设计变量 |

`main.tsx` 依次导入 `tokens.css`、`base.css`。旧的 `src/styles.css` 在第 3 个 PR 删除。

### 3.2 设计变量（沿用参考版取值）

```css
/* 用途：tokens.css 的变量清单；实施时写入该文件 */
--ink: #0E1419;          /* 机箱底色 */
--ink-raised: #161E26;   /* 卡片 */
--ink-sunk: #0A0F13;     /* 输入框、凹槽 */
--ink-line: #26313B;     /* 分隔线、遮罩色块 */
--ink-line-2: #38454F;   /* 悬停边框 */
--lamp: #F0A22E;         /* 琥珀读数灯：强调色 */
--lamp-soft: #F0A22E22;
--lamp-ink: #171104;     /* 琥珀底上的文字 */
--signal: #6FD3C7;       /* 成功 */
--danger: #E4685D;       /* 失败、删除 */
--danger-soft: #F3AAA3;
--chalk: #E6EDF3;        /* 正文 */
--chalk-dim: #8494A1;
--chalk-faint: #5C6975;
--font-ui / --font-read / --font-mono   /* 同参考版的系统字体栈，不加载网络字体 */
--r-sm: 4px; --r-md: 8px; --r-lg: 14px;
--pad: clamp(16px, 3vw, 32px);
--dur-fast: .15s; --dur-base: .2s;
--z-topbar: 40; --z-modal: 60; --z-toast: 70;
--shadow-pop: 0 8px 28px #00000080;   /* toast、弹层阴影 */
--backdrop: #0A0F13D1;               /* 弹层遮罩 */
--topbar-h: 58px;
```

### 3.3 约定

- 类名 camelCase（`styles.reelRow`），由 stylelint `selector-class-pattern` 约束。
- 组件状态用 `data-*` 属性表达（如 `data-veiled`、`data-current`、`data-status`、`data-dragging`），CSS 用属性选择器，不拼接修饰类名。
- 除 `tokens.css` 外，所有样式文件（含 `base.css`）禁止直接写颜色值（stylelint：`color-no-hex`、`color-named: "never"`、`function-disallowed-list` 禁用 `rgb/rgba/hsl/hsla`）；半透明色用 `color-mix()` 基于变量生成。
- 测试只按角色、可见文字、label 或 `data-*` 查询，不依赖类名。
- TypeScript：新增 `src/vite-env.d.ts`（`/// <reference types="vite/client" />`），让 `import styles from "./X.module.css"` 在严格模式下有类型。
- Vitest：`test.css.modules.classNameStrategy` 设为 `"stable"`，只为不报错。

### 3.4 stylelint

- 开发依赖：`stylelint`、`stylelint-config-standard`、`stylelint-config-css-modules`。
- 配置文件：`apps/web/stylelint.config.js`；`tokens.css` 通过 `overrides` 放开颜色规则。
- `lint` 脚本改为 `eslint . && stylelint "src/**/*.css"`。

## 4. 目录与组件分层

```text
用途：目标目录结构，不是命令
src/
├─ styles/                tokens.css、base.css
├─ components/            与业务无关的通用组件，每个一个目录（组件 + 样式 + 测试）
│  ├─ Button/             variant: primary | ghost | transport | reveal
│  ├─ Field/              Field（标签+控件）、RangeField（滑块+数值读数）
│  ├─ Modal/              Modal、ModalProvider、useModalOpen
│  ├─ ConfirmDialog/
│  ├─ Toast/              ToastProvider、useToast
│  └─ ProgressBar/
├─ app/
│  ├─ AppShell/           布局路由：顶栏 + <Outlet/> + 快捷键面板
│  ├─ router.tsx、queryClient.ts
├─ features/
│  ├─ intake/             IntakeCard、SourceForm、FilePicker、SettingsDrawer、processing.ts
│  ├─ jobs/               JobList、JobCard、ProgressOverlay、useJobs.ts
│  └─ practice/           Readout、VeiledSentence、SentenceProgress、Transport、PlaybackSettings、
│                         PracticeActions、SentenceReel、ResegmentDialog、hotkeys.ts、useHotkeys.ts、
│                         playerReducer.ts、PlayerProvider.tsx、playhead.ts、useAudioController.ts
└─ pages/                 LibraryPage、PracticePage（只做数据分支与组合）
```

依赖方向：`pages → features → components → styles`；`components` 不引用 `features` 与 `api`。

## 5. 通用组件与行为层

### 5.1 Button

`<Button variant="primary|ghost|transport|reveal" ...buttonProps>`；链接外观的下载按钮用 `<ButtonLink>`（渲染 `<a>`，共享样式）。`transport` 为方形走带按钮，必须提供 `aria-label`。

### 5.2 Field / RangeField

- `Field`：`label` + 任意控件，标签为等宽小号大写样式。
- `RangeField`：`<input type="range">` + 数值读数（如「最短句 1.0s」），读数用 `<output>` 关联。

### 5.3 Modal

```tsx
// 用途：接口草案，实施时以此为准
type ModalProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  returnFocusTo?: RefObject<HTMLElement | null>;
  children: ReactNode;
};
```

- 打开时焦点移入第一个可聚焦元素；Tab/Shift+Tab 在弹层内循环；Escape 调用 `onClose`；关闭后焦点回到 `returnFocusTo`（默认为打开前的活动元素）。
- 遮罩背景 + 模糊，`role="dialog"`、`aria-modal="true"`、`aria-labelledby` 指向标题。
- `ModalProvider` 统计当前打开的弹层数，`useModalOpen()` 返回是否有任何弹层打开；播放器快捷键据此整体暂停。
- 使用方：ResegmentDialog、快捷键面板、ProgressOverlay、ConfirmDialog。

### 5.4 ConfirmDialog

基于 Modal 的确认框：标题、说明、「取消」与危险样式的确认按钮。替代素材库删除时的 `window.confirm`。

### 5.5 Toast

- `ToastProvider` 放在 AppShell；`useToast()` 返回 `notify(message, kind?: "info" | "error")`。
- 一次只显示一条，新提示替换旧提示；info 3 秒、error 6 秒自动消失。
- 容器是常驻的两个播报区：info 用 `aria-live="polite"`，error 用 `aria-live="assertive"`。不使用 `role="status"` / `role="alert"`，避免与页面里已有的状态、警告角色重名。
- 使用场景：快捷键操作反馈、重新切分完成、后台任务完成或失败。表单校验与提交错误仍显示在表单旁。

### 5.6 ProgressBar

`<ProgressBar value={0..1} label={string} />`，提供 `role="progressbar"`、`aria-valuenow`（0–100）、`aria-valuetext`。

### 5.7 播放进度订阅（修 Minor 4）

- `playhead.ts` 提供 `createPlayhead()`：`{ get(): number; set(t: number): void; subscribe(listener): unsubscribe }`。
- `PlayerProvider` 创建一个实例放入 Context；`useAudioController` 在 RAF 与 `timeupdate` 中调用 `set`，不再持有 React state。
- `usePlayhead()` 基于 `useSyncExternalStore`，只有 VeiledSentence、Readout 的时间项、SentenceProgress 订阅；SentenceReel、Transport、PlaybackSettings 在播放时不重渲染。

### 5.8 快捷键（修 Minor 1、2）

- `hotkeys.ts` 导出唯一的按键表：`{ key, action, label, description }[]`。`useHotkeys` 的映射和快捷键面板的说明都从这张表生成。
- 焦点规则：

| 聚焦元素 | 行为 |
|---|---|
| 文本输入框（text/search/number/url 等）、`textarea`、可编辑区域 | 屏蔽全部快捷键 |
| 复选框、单选框 | 只把 Space 留给控件，其余快捷键照常 |
| 下拉框 | 只把方向键、Space、Enter 留给控件，其余照常 |
| 按钮、链接 | 只把 Space、Enter 留给控件，其余照常 |
| 其他 | 全部快捷键生效 |

- 带 Ctrl/⌘/Alt 的组合键与输入法组字中的按键不处理。
- 有弹层打开时快捷键整体暂停。全局不再处理 Escape，Escape 由 Modal 处理；搜索框中的 Escape 交给浏览器清空。
- 按 L、`[`、`]`、A 时通过 toast 反馈新值（「循环：每句 3 遍」「语速 0.90×」「自动下一句：开」）。

### 5.9 播放器 reducer 调整

- 新增 `listenCounts: ReadonlyMap<number, number>`：每次 `completed` 为当前句加 1；`reset` 清空。
- 「与句子等长」留白 = `sentence.duration / rate`（Provider 中计算）。
- 其余事件语义不变。

## 6. 应用外壳

- 布局路由 `AppShell` 包住 `/` 与 `/jobs/:jobId`，内含 `ToastProvider`、`ModalProvider`。
- 顶栏吸顶、半透明加模糊：左侧琥珀指示灯 + 等宽品牌字 `loop/lish`（斜杠为琥珀色）；右侧幽灵按钮「素材库」（路由链接）与「快捷键」（打开快捷键面板）。
- `index.html`：`lang="zh-CN"`、标题「Looplish · 逐句听力台」、参考版风格的 SVG favicon、`theme-color` 为 `--ink`。

## 7. 素材库页

居中单栏（最大宽度约 760px）：投放卡片 → 「已处理的素材」分组标题 → 任务列表。

### 7.1 投放卡片 IntakeCard

- 整张卡片是拖放区，拖入时 `data-dragging` 使边框变琥珀色。
- 衬线大标题「把一段视频拆成一句一句来听」，下接一行说明。
- SourceForm：等宽输入框 + 主按钮「开始切分」；是否接受本机路径、提示文案沿用现有逻辑。
- FilePicker：幽灵按钮「选择本地文件」（视觉隐藏的 file input，键盘可用）+ 提示「也可以直接拖放到这个区域」。选中或拖入后显示「已选择：name ［上传并处理］［取消］」；类型不像音视频时附一行提示，仍允许上传。
- SettingsDrawer（`<details>`「识别与切分设置」，默认折叠）：
  - 识别引擎（下拉，来自运行配置）、字幕来源（下拉：优先用自带字幕 / 总是重新识别 / 只用自带字幕）。
  - 语言：可自由输入，附常用语言建议（`<datalist>`），留空表示自动检测。
  - 「预先生成全部单句音频」开关。
  - 5 个切句参数用 RangeField，范围沿用 `SEGMENT_LIMITS`。
  - 参数不合法时抽屉自动展开并列出原因，两个提交入口禁用。

### 7.2 任务列表 JobList / JobCard

- 每个任务一张卡片：标题 + 等宽元信息「24 句 · 09-30 17:40 · bilibili.com」；右侧状态文字（已完成 / 处理中·转写 / 排队中 / 失败），`data-status` 着色。
- 已完成的任务整张卡片可点击进入练习台：标题是唯一的链接，通过伪元素扩大点击区域。
- 处理中的卡片底部显示 ProgressBar 与百分比；失败的卡片多一行失败原因。
- × 删除按钮（读屏名称「删除 xxx」），处理中禁用，点击后用 ConfirmDialog 确认。
- 空列表、加载中、连接中断各显示一行说明；重试与退避仍由查询层负责。

### 7.3 处理进度浮层 ProgressOverlay

- 链接提交或上传成功后打开，跟踪返回的任务 ID。
- 数据来自素材库列表查询里的该任务；列表尚未包含它时使用提交接口返回的 Job。不新增轮询。
- 处理中：标题、ProgressBar、琥珀色阶段说明、「可以放到后台，任务会继续处理」、「放到后台」按钮。
- 成功：「处理完成 · 共 N 句」，按钮「开始练习」（进入练习台）与「留在素材库」。
- 失败：失败原因与「关闭」。
- 后台提示：任务在素材库页上从处理中变为终态、且浮层没有正在显示它时，toast「「标题」处理完成」或「……处理失败」（error）；每次状态变化只提示一次。

## 8. 练习台

### 8.1 布局

宽屏两栏：左侧播放台约 55%，`position: sticky` 停在顶栏下方；右侧句子清单。宽度 < 960px 时单栏，播放台不固定；< 560px 时走带按钮收紧、揭晓按钮占满一行、清单隐藏时间列。

### 8.2 播放台

1. 标题行：「← 素材库」幽灵按钮 + 灰色素材标题（省略号截断）。
2. Readout（等宽数字）：琥珀大号「3 / 24」、「循环 2/3」、「听了 5 次」（`listenCounts`）、本句内时间「00:01.2」、句长「2.9s」；留白期间显示「跟读中」指示灯。
3. VeiledSentence：衬线大字。遮罩时词保留在 DOM 中但文字透明、显示为 `--ink-line` 色块，禁止选中，容器对读屏隐藏并另附「文本已隐藏，共 N 个词」；当前词在遮罩时色块变琥珀色、揭晓时文字变琥珀色。无词级时间时按空格拆词显示、不高亮。
4. SentenceProgress：细进度条，宽度 = (当前时间 − start) / (end − start)，对读屏隐藏。
5. Transport：◀◀ ▶/❚❚ ↻ ▶▶（`aria-label` 为上一句 / 播放或暂停 / 重听 / 下一句，`title` 附快捷键）；右侧 reveal 按钮「显示原文 / 遮住原文」，`aria-pressed`。
6. PlaybackSettings：循环（不循环 / 每句 2、3、5 遍 / 一直重复）、语速（0.60×–1.25×，步长 0.05）、跟读间隔（0、1、2、3、5 秒 / 与句子等长）、开关「自动下一句」「换句自动遮住」。
7. PracticeActions：ButtonLink「下载 SRT」「下载 VTT」「下载文本」「学习包 ZIP」（地址来自 `api.urls`）+「重新切分」。
8. 播放被拒、音频加载失败、后台刷新失败的提示显示在 Transport 上方。

### 8.3 句子清单 SentenceReel

- 表头：分组标题「全部句子」、「已练 5 / 24」、搜索框。
- 行：序号 | 起始时间 | 原文（两行截断）。当前行 `data-current` + `aria-current`，琥珀左边框与淡色底；已练行原文变灰并显示「已练」。
- 当前句处于遮罩状态时，整列原文模糊、`aria-hidden`，行的读屏名称为「第 N 句 0:03」；搜索时命中项始终清晰。
- 当前句变化时滚动到可见区域（`block: "nearest"`）。

### 8.4 重新切分

ResegmentDialog 改用 Modal；5 个参数保持数字输入框（留空 = 沿用旧值，滑块无法表达），输入框提示取值范围；成功后 toast「重新切分完成，共 N 句」，其余行为不变。

### 8.5 非就绪状态

排队 / 处理中（ProgressBar + 阶段说明）、失败、空结果、任务不存在，都用同风格的居中卡片显示，并带「← 素材库」。已有数据时后台刷新失败保持播放器不变（沿用 PR #19 的修复）。

## 9. 测试、验证与交付

### 9.1 测试

- 现有 reducer、素材库、练习台行为测试全部保留，查询方式迁移为角色 / 文字 / label / `data-*`。
- 有意改变的行为同步改写测试：删除确认改为 ConfirmDialog；「与句子等长」留白按语速换算；快捷键焦点规则；Escape 由弹层处理。
- 新增：
  - Modal：焦点移入、Tab 循环、Escape 关闭、焦点返回、打开期间快捷键暂停。
  - Toast：显示时长、替换。
  - 快捷键焦点规则：按「控件类型 × 按键」表逐格验证。
  - 播放进度订阅：播放时 SentenceReel 与 PlaybackSettings 不重渲染（渲染计数）。
  - Readout：「听了 N 次」递增与重置。
  - ProgressOverlay：处理中 / 成功 / 失败 / 放到后台。
  - 后台完成 toast 只出现一次。

### 9.2 质量门禁

每个 PR：`format:check`、`lint`（ESLint + stylelint）、`typecheck`、全部测试、`build`。

### 9.3 人工验证

- 用种子数据（有词级时间、无词级时间、空结果、失败任务）启动本机前后端，逐项对照第 6–8 节。
- 截取两个页面在 1280px 与 375px 宽度下的截图附在 PR 中。

### 9.4 交付：3 个依次合并的 PR

| PR | 分支 | 内容 |
|---|---|---|
| 1 基础设施 | `feat/console-ui-foundation` | 本设计文档；tokens/base、CSS Modules 类型、stylelint；Button、Field、Modal、ConfirmDialog、Toast、ProgressBar；AppShell 与快捷键面板；快捷键表与焦点规则；播放进度订阅；reducer 的 `listenCounts` 与留白换算。两个页面暂用旧样式，功能不变 |
| 2 素材库 | `feat/console-ui-library` | IntakeCard、SettingsDrawer、JobList/JobCard、ProgressOverlay、后台完成提示 |
| 3 练习台 | `feat/console-ui-practice` | 两栏布局、Readout、VeiledSentence、SentenceProgress、Transport、PlaybackSettings、PracticeActions、SentenceReel、ResegmentDialog 接入 Modal；删除 `src/styles.css` |

每个 PR 的 diff 控制在 AI 评审可完整读取的范围内（约 100KB）。
