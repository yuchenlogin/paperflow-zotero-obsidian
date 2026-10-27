# PaperFlow

把 Zotero 中的论文生成可继续积累的 Obsidian 中文阅读笔记：补足研究背景、逐模块讲解方法、用表格呈现实验，并与知识库里已有论文建立有解释的联系。

这是从实际个人工作流整理出的 **2.2.0 公开预览版**。核心流程为 Obsidian 桌面插件 + 本地 Python 后端；附带可分发的 Codex skill。支持 OpenAI-compatible API 或复用本机 Codex CLI 登录，无需 Zotero 云端 API key。

检查覆盖离线 Python 测试、Node 插件测试、安装与打包、Codex CLI 输入/失败路径及 Obsidian 格式。具体验证与版本限制见 CHANGELOG；离线测试不调用模型，不接触真实文库。

## 已实现与验证范围

- Obsidian 按 Zotero **标题子串**搜索，选择后生成新笔记或打开已有笔记。
- 读取本机个人文库的 DB/WAL 一致性副本，不写 Zotero 数据库；支持存储型 PDF 及绝对路径的本地 PDF。
- 全文逐页提取 → 连续引文核验 → 全文综合分析 → 结构、数值出现及关系链接检查 → 写入笔记。没有可提取完整 PDF 时停止，不把摘要冒充精读。
- Zotero 条目链接、PDF 物理页链接、方法与结果原文页图、Mermaid 方法图、折叠自测答案。
- 原文出处与自测答案使用 Obsidian 原生可折叠 callout；发布前检查 HTML 混排、表格列数、代码围栏与引用格式。
- 提示词明确禁止防御性写作、套话和重复提醒，保留有具体证据与影响的实质局限。
- 重生成通过 Obsidian 编辑器合并，保存历史，保留 `<!-- PAPERFLOW:PERSONAL -->` 之后的个人记录；生成期间属性/AI 正文变化则停止覆盖。
- 已在 macOS 的实际个人文库上跑通过原有 2.0 工作流和单篇重生成。2.1 的可移植打包另有离线测试；Linux 列为目标平台，尚未做真实桌面端全流程验证。

**Zotero Bridge 是可选实验源码**：右键 Zotero → Obsidian 的入口仍缺少成功安装及端到端验证，未进入插件市场。不要把它当作默认安装条件。默认入口是 Obsidian。

## 环境

macOS/Linux，Python 3.10+，Obsidian Desktop 1.5+，本机 Zotero 个人文库，Poppler（`pdftotext` / `pdftoppm`）和 `curl`。测试和构建还需 Node.js 20+。不支持原生 Windows、移动端、Zotero 群组文库、扫描件 OCR 或全文语义检索。

macOS 可用 `brew install python poppler`；Debian/Ubuntu 可用发行版包管理器安装 `python3-venv poppler-utils curl`。本项目不分发这些第三方程序。

## 安装

从 [Releases](https://github.com/yuchenlogin/paperflow-zotero-obsidian/releases) 下载源码包，或 clone 项目：

```sh
git clone https://github.com/yuchenlogin/paperflow-zotero-obsidian.git
cd paperflow-zotero-obsidian
```

在项目根目录执行下列命令，将路径换成自己的已有知识库绝对路径：

```sh
python3 scripts/install.py --vault "/absolute/path/to/vault" --dry-run
python3 scripts/install.py --vault "/absolute/path/to/vault"
python3 -m venv "/absolute/path/to/vault/.paperflow/venv"
"/absolute/path/to/vault/.paperflow/venv/bin/python" -m pip install -r requirements.txt
```

如果 Zotero 数据目录不是 `~/Zotero`，退出 Obsidian 后在安装时加 `--zotero-dir "/absolute/path/to/Zotero" --obsidian-closed`，或在 Obsidian → PaperFlow 设置填写 **Zotero 数据目录**。命令行写插件设置时要求 Obsidian 已退出，安装器也会阻止并行安装。这是含 `zotero.sqlite` 的数据目录，不是 Firefox profile 目录。

编辑知识库 `.paperflow/config.json`，填入自己所用的 OpenAI-compatible Chat Completions 服务：

```json
{
  "base_url": "https://your-provider.example/v1",
  "api_key": "YOUR_KEY",
  "model": "YOUR_MODEL",
  "max_tokens": 16000
}
```

模型需支持 JSON object 输出、长上下文和足够长的中文正文。全文最长 200,000 字符；这只是程序预算，不保证服务商上下文足够。服务商限额、价格与模型效果请自行核对。环境变量 `PAPERFLOW_API_KEY`、`PAPERFLOW_BASE_URL`、`PAPERFLOW_MODEL` 可覆盖对应字段，`PAPERFLOW_CONFIG` 可指向知识库外的配置文件。

### 使用本机 Codex 登录

先在本机安装 Codex CLI 并完成 `codex login`，然后将 `.paperflow/config.json` 设为：

```json
{
  "transport": "codex-cli",
  "codex_path": "codex",
  "codex_timeout": 600
}
```

配置示例也在 `config.codex.example.json`。桌面程序找不到 `codex` 时填写可执行文件绝对路径。模型与推理强度读取 `${CODEX_HOME:-~/.codex}/config.toml` 的基础配置；`codex_model` 或 `PAPERFLOW_CODEX_MODEL` 可显式选择模型，`PAPERFLOW_CODEX_PATH` 可覆盖程序路径。已有 API 配置不写 `transport` 时仍使用原来的 API 路径；`PAPERFLOW_TRANSPORT` 可切换传输方式。

当前适配范围是 **Codex CLI 0.155.1** 的原生 OpenAI/ChatGPT 登录 provider，不支持 Codex profile 或带自定义地址/密钥字段的 provider；这些服务请使用 API 模式。其他 CLI 版本会停止运行，需重新验证工具边界后再适配。

PaperFlow 调用临时、只读的 `codex exec`，通过临时模型能力目录和功能开关移除 shell、文件、浏览、MCP/apps 等工具；真实 CLI 的本地模拟服务测试确认请求的 `tools` 为空。该目录只约束客户端能力，不改变请求的模型名称。不读取或复制 `auth.json`，不把令牌转换为 API key，也不保留 CLI 会话或完整请求日志。论文仍会发送给当前 Codex 模型，并使用该登录的额度。用量、登录或网络失败会停止，不切换模型或自动重复请求。

每次 CLI 请求最多 600 秒，证据与正文校验各最多修正一次；桌面任务总超时为 50 分钟。更新代码只影响以后生成，现有笔记不会自动重写。

重新加载 Obsidian，在设置 → 第三方插件中启用 **PaperFlow**。首次使用图表时允许 Obsidian 显示 Mermaid。运行检查：

```sh
"/absolute/path/to/vault/.paperflow/venv/bin/python" scripts/doctor.py --vault "/absolute/path/to/vault"
```

Doctor 只检查依赖、路径和配置是否填写；不会调用模型，也不证明服务凭据或 Zotero schema 一定兼容。

## 使用

在 Obsidian 按 `Cmd/Ctrl+P`，搜索 `PaperFlow`：

| 命令 | 用途 |
| --- | --- |
| 选择 Zotero 论文（按标题，生成或打开） | 标题子串搜索；不区分大小写 |
| 从 Zotero 链接或 key 生成 | 输入个人文库论文父条目的八位 key 或 select 链接 |
| 从剪贴板 Zotero 链接生成 | 使用已复制的 select 链接 |
| 重新生成当前论文的 AI 区域（保留我的记录） | 重新调用模型，保护个人记录、保留旧版 |

也可点击左侧书本图标。生成通常需要数分钟，取决于 PDF 和模型。已有笔记默认直接打开，不重复调用模型。新笔记在 `Papers/`，图表在 `Assets/Papers/<key>/`；论文目录与模板可在设置中修改，不要求重组整个知识库。

标题、作者、标签、笔记或 PDF 全文的复杂搜索请用 Zotero 自带搜索：[官方说明](https://www.zotero.org/support/searching)。PaperFlow 的选择器当前只按标题筛选。

完整操作与保护规则见 [使用说明](docs/usage.md)，数据流见 [架构与隐私](docs/architecture.md)。

## Codex skill

仓库里的 [skills/paperflow/SKILL.md](skills/paperflow/SKILL.md) 可复制整个 `skills/paperflow` 文件夹到 `~/.codex/skills/` 后使用；也可下载 Release 中的 `paperflow-skill-2.2.0.zip`，将其 `paperflow` 文件夹解压到该位置。**skill 负责调用已安装的后端，不替代安装**。例如：“用 PaperFlow 在我的 Zotero 里搜索 domain generalization，并生成选中论文的 Obsidian 笔记。”

独立运行相同入口：

```sh
"/absolute/path/to/vault/.paperflow/venv/bin/python" skills/paperflow/scripts/run.py --vault "/absolute/path/to/vault" --query "tracking"
"/absolute/path/to/vault/.paperflow/venv/bin/python" skills/paperflow/scripts/run.py --vault "/absolute/path/to/vault" --key ABCD1234
```

`ABCD1234` 是格式示例，须换成真实父条目 key。此脚本打印笔记路径，不操纵 Obsidian 窗口；重生成请用 Obsidian 命令完成编辑器协调合并。

## 升级、开发与发布

更新源码后执行安装命令并加 `--upgrade`：不同的受管理代码会先备份到 `.paperflow/install-backups/`。现有 `config.json`、模板与插件设置默认保留，升级不自动修改笔记。更换后端依赖后重新运行 pip 安装，重载插件。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONPATH=backend .venv/bin/python -m unittest discover -s tests -v
node tests/test_plugin.js
.venv/bin/python scripts/build.py
```

`dist/` 生成源码包、独立 skill ZIP、实验 Bridge XPI 和 `SHA256SUMS.txt`；源码包仅包含显式允许的文件。CI 运行离线测试，不接触真实 Zotero 数据或模型服务。测试使用合成数据，仓库不包含真实文库、论文 PDF、用户笔记、API key 或生成历史。

项目自有代码以 [MIT](LICENSE) 许可发布；依赖和论文内容保留各自权利。`zotero-bridge/` 目前仅供开发验证，尚无市场安装支持。

## 限制

机器检查能确认引文在指定页出现、章节和链接存在，能做部分数值检查；**不能证明语义、公式解释、任务关系或比较结论全部正确**。笔记保持 AI 生成与未读状态，需要读者核查。当前引文策略面向有方法、训练和实验章节的实证论文，综述/理论论文可能因证据类型不足而停止。

模型请求会发送完整论文、书目元数据，以及已有论文笔记的标题与 `summary` 属性用于关系分析。个人记录正文不进入模型输入；如果你把私人内容放入 `summary`，它也会发送。隐藏目录和 `.gitignore` 不等于 Obsidian Sync、iCloud 或网盘排除；请自行设置同步范围，优先把密钥配置放在知识库外。
