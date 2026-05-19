# PaperPilot

[![PyPI](https://img.shields.io/pypi/v/paperpilot?color=2563eb&label=PyPI)](https://pypi.org/project/paperpilot/)
[![Python](https://img.shields.io/pypi/pyversions/paperpilot?color=0f766e&label=Python)](https://pypi.org/project/paperpilot/)
[![License](https://img.shields.io/github/license/CHB-learner/PaperPilot?color=f59e0b)](LICENSE)
[![Release](https://img.shields.io/github/v/release/CHB-learner/PaperPilot?color=7c3aed&label=Release)](https://github.com/CHB-learner/PaperPilot/releases)
[![CLI](https://img.shields.io/badge/CLI-PaperPilot-334155)](https://github.com/CHB-learner/PaperPilot)
[![Reports](https://img.shields.io/badge/Reports-ZH%2FEN%20MD%20HTML%20PDF-ef4444)](https://pypi.org/project/paperpilot/)
[![Workflow](https://img.shields.io/badge/Workflow-evidence--grounded-0891b2)](https://github.com/CHB-learner/PaperPilot)
[![在线体验](https://img.shields.io/badge/在线体验-Cloudflare%20Workers-f38020)](https://paperpilot.aleck-757.workers.dev/)
[![Netlify 在线体验](https://img.shields.io/badge/在线体验-Netlify-00ad9f)](https://voluble-marshmallow-e2bba5.netlify.app/)

[English](README.md) | [中文](README.zh-CN.md) | [项目主页](https://chb-learner.github.io/PaperPilot/) | [GitHub](https://github.com/CHB-learner/PaperPilot) | [PyPI](https://pypi.org/project/paperpilot/)
[在线体验：Cloudflare Workers](https://paperpilot.aleck-757.workers.dev/) | [在线体验：Netlify](https://voluble-marshmallow-e2bba5.netlify.app/)

<p align="center">
  <a href="https://www.star-history.com/#chb-learner/paperpilot&Date">
    <img src="https://api.star-history.com/svg?repos=chb-learner/paperpilot&type=Date" alt="PaperPilot GitHub star history" width="100%">
  </a>
</p>

<p align="center">
  <img src="docs/assets/paperpilot-hero.png" alt="PaperPilot - scholarly literature review agent" width="100%">
</p>

PaperPilot 是一个面向 AI、生医与 AI for Science 场景的 **CLI 科研文献检索与综述 Agent**。  
它把自然语言研究需求，转化为可追踪、可复现的工作流，并输出中文/英文一致的三端报告（Markdown、HTML、PDF）。

Cloudflare Workers 在线体验提供轻量浏览器入口：服务端使用 OpenAI-compatible LLM 生成检索计划，调用公开论文 metadata 源返回候选论文，并支持下载轻量 Markdown/HTML 报告。完整的语料筛选、PDF/全文处理、Evidence Ledger、中英 PDF 报告和 Obsidian Wiki 仍由本地 CLI workflow 提供。

该项目是文件系统驱动的研究工作流，而不是聊天机器人：每次运行都会生成独立的 task 文件夹，完整保留状态、事件日志和中间产物。

## ✨ 我能做什么

- 自然语言解析研究意图，自动形成可执行检索任务
- 生成检索协议与纳入/排除标准
- 多源检索（免费源 + 可选 API 源）并进行统一标准化
- 重排、去重、核心语料筛选与相关性分类
- 校验 DOI/URL/PDF/代码链接可达性（不绕过付费墙）
- 生成带证据链的综述正文与对照矩阵
- 输出完整 run folder 与可追溯日志

## 🚀 特性亮点

### 交互体验
- Rich 终端交互，支持颜色与分组菜单
- Cloudflare Workers 在线体验：生成检索计划、查询公开论文源、下载轻量 Markdown/HTML 报告
- 启动页显示当前模型、来源配置与快捷命令
- 支持 `/model`、`/sources`、`/doctor`
- 支持命令模式与交互模式统一工作流

### 检索与筛选
- Query 理解 + 检索计划 + 关键词多样化
- 统一 `Paper` 数据模型
- DOI、arXiv、PMCID/PMID、标题相似度等多级去重
- 核心 / 相关 / 排除三类筛选
- GitHub、GitLab、Hugging Face、项目页等代码链接解析
- 下载开放 PDF（或可选跳过），并提取全文

### 质量与报告
- `quality gate`、反思重检、Evidence Ledger
- Review Agents（来源核验、相关性、引证合规、越界断言检测）
- Canonical report model 驱动中英报告一致
- 论文统一编号引用（[1][2][3]）并自动体现在参考文献中
- Markdown / HTML / PDF 输出一致且可对齐
- 在线体验可下载基于公开 metadata/abstract 的轻量 Markdown/HTML 简报
- 最终报告默认最多 100 篇文献，不再强制最低 30 篇
- 默认生成 Obsidian Wiki：论文页、方法页、主题页、claim 页和知识图谱入口

## 🗂 已集成来源

默认免费来源：

- arXiv
- Semantic Scholar
- OpenAlex
- Crossref
- OpenReview
- PubMed / NCBI E-utilities
- Europe PMC
- bioRxiv / medRxiv
- DBLP
- ACL Anthology
- Papers.cool

可选 API-key 来源：

- DeepXiv / Agentic Data
- CORE
- Lens.org Scholarly API
- IEEE Xplore
- Springer Nature
- Elsevier / Scopus
- Dimensions

## 🛠 安装

从 PyPI 安装：

```bash
python -m pip install paperpilot -i https://pypi.org/simple
```

本地开发安装：

```bash
git clone https://github.com/CHB-learner/PaperPilot.git
cd PaperPilot
python -m pip install -e .
```

## ⚙️ LLM 与来源配置

PaperPilot 需要 OpenAI-compatible 的 LLM 配置才能完成解析、规划、综合和报告生成。首次运行会自动生成可编辑模板：

```text
~/.paperpilot/config.json
```

模板示例：

```json
{
  "active": "default",
  "profiles": {
    "default": {
      "api_key": "",
      "base_url": "",
      "model": "gpt-5.2"
    }
  },
  "sources": {
    "core": {"enabled": null, "api_key": "", "base_url": ""},
    "lens": {"enabled": null, "api_key": "", "base_url": ""},
    "ieee": {"enabled": null, "api_key": "", "base_url": ""},
    "springer": {"enabled": null, "api_key": "", "base_url": ""},
    "elsevier": {"enabled": null, "api_key": "", "base_url": ""},
    "dimensions": {"enabled": null, "api_key": "", "base_url": ""},
    "deepxiv": {"enabled": null, "api_key": "", "base_url": ""}
  }
}
```

说明：

- 可选来源不填 key 不会启用，`enabled: null` 表示“有 key 后自动启用”。
- 配置文件支持直接编辑，也可通过 CLI 命令管理。

命令示例：

```bash
PaperPilot config set --base-url https://api.deepseek.com --model deepseek-chat
PaperPilot config import ./api.json
PaperPilot config list
PaperPilot config use deepseek
PaperPilot config show
PaperPilot --doctor
```

```bash
PaperPilot sources list
PaperPilot sources config core
PaperPilot sources config deepxiv
PaperPilot sources enable core
PaperPilot sources test core
```

交互内可用 `/sources` 与 `/doctor` 快速查看与复查来源配置。

### Cloudflare Workers 在线体验配置

线上体验运行在 `https://paperpilot.aleck-757.workers.dev/`，由 Cloudflare Worker 提供 `/api/literature-search`。`wrangler.jsonc` 内置安全默认值：

```text
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
LLM_API_KEY=123456
```

请在 Cloudflare `Variables and Secrets` 中用真实服务端 key 覆盖占位的 `LLM_API_KEY`。前端只调用 Worker API，不会在浏览器代码中嵌入密钥。在线体验默认使用 OpenAlex 和 Crossref 公开 metadata 源；Semantic Scholar 仅在配置 `SEMANTIC_SCHOLAR_API_KEY` 后启用，以避免公开 API 限流。

可选来源 API 获取入口：

| 来源 | 获取入口 |
|---|---|
| CORE | https://core.ac.uk/services/api |
| Lens.org | https://docs.api.lens.org/ |
| IEEE Xplore | https://developer.ieee.org/getting_started |
| Springer Nature | https://dev.springernature.com/ |
| Elsevier / Scopus | https://dev.elsevier.com/ |
| Dimensions | https://docs.dimensions.ai/dsl/api.html |
| DeepXiv / Agentic Data | https://data.rag.ac.cn/api/docs |
| Papers.cool | https://papers.cool |

配置优先级：

1. 环境变量：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`
2. 用户配置：`~/.paperpilot/config.json`
3. 兼容文件：`llmapi.txt`

## 🧪 快速上手

交互模式（推荐）：

```bash
PaperPilot
```

命令行模式：

```bash
PaperPilot "RNA inverse folding sequence design" \
  --auto-confirm \
  --max-papers 50 \
  --since-year 2021 \
  --github-filter required \
  --sources auto \
  --mode apa \
  --quality balanced
```

导入本地语料：

```bash
PaperPilot "RNA inverse folding sequence design" \
  --auto-confirm \
  --user-corpus ./papers \
  --user-corpus references.bib \
  --no-download
```

任务管理：

```bash
PaperPilot inspect runs/<task-id>
PaperPilot resume runs/<task-id>
```

## 🧭 流程架构

PaperPilot 的工作流为：

```text
Intake -> Protocol -> Search -> Corpus -> Screening -> Verification -> Synthesis -> Review -> Report
```

```mermaid
flowchart LR
  U["用户需求"] --> C["运行上下文"]
  C --> QA["需求理解"]
  QA --> PL["规划与协议"]
  PL --> ST["Source Registry 检索"]
  ST --> NB["语料标准化"]
  NB --> SC["核心 / 相关 / 排除分类"]
  SC --> VF["验证 + PDF / 代码检查"]
  VF --> LM["文献矩阵"]
  LM --> QG["Quality Gate"]
  QG --> EL["Evidence Ledger"]
  EL --> RP["报告渲染：中英"]
```

附带架构说明页：

- `paperpilot_agent_flow.html`

## 📁 产物目录

每次任务默认落在 `runs/<task-id>/`（或 `--output-dir` 指定目录），核心文件包括：

- `task.json`、`state.json`、`events.jsonl`、`manifest.json`
- `planning/`：关键词理解、检索计划、研究协议、Prompt/Registry 清单
- `search/`：原始标准化论文元数据和来源诊断
- `corpus/`：完整语料、核心/邻近/排除集合、最终报告论文
- `verification/`：验证结果、质量门、反思、下载日志、证据账本、复核结果
- `synthesis/`：证据矩阵和综合分析
- `reports/`：`report.canonical.json`、中英文 Markdown、HTML、PDF 报告
- `assets/pdfs/` 与 `assets/fulltext/`：开放 PDF 和全文抽取结果
- `wiki/obsidian/`：Obsidian 知识图谱目录

## 🧠 Obsidian Wiki

每次成功运行默认都会生成：

```text
runs/<task-id>/wiki/obsidian/
```

这个目录可以直接作为 Obsidian vault 打开，核心结构包括：

- `index.md`：本次调研入口、研究问题和报告论文总览
- `papers/`：一篇论文一个 note，包含引用编号、PDF/代码链接、方法流派和证据基础
- `methods/`：主流方法流派页，链接代表论文
- `topics/`：关键词、子方向和检索主题页
- `claims/`：证据 claim 页，绑定引用论文
- `_meta/manifest.json`、`_meta/wiki_lint.json`：来源追踪、hash、broken wikilink 检查

如需跳过 Wiki 生成，可使用 `--no-obsidian-wiki`。

如果需要公开文档里的 ScholarFlow 风格 vault 结构和配置模板，请使用已脱敏示例：

- [`docs/scholarflow-vault-example.md`](docs/scholarflow-vault-example.md)
- [`examples/scholarflow.example.json`](examples/scholarflow.example.json)

`summary.md` 自动索引表示例：

| 发布时间 | 论文 | 笔记 | 代码 | 来源 | 备注 |
|---|---|---|---|---|---|
| 2026.05.20 | [CitationGraph-RAG](https://example.org/papers/citationgraph-rag) | 待精读 | [GitHub](https://github.com/example/citationgraph-rag) | [arXiv](https://arxiv.org/) | 公开演示行 |
| 2026.05.18 | [BenchAgent-Eval](https://example.org/papers/benchagent-eval) | 草稿笔记 |  | [OpenReview](https://openreview.net/) | 脱敏示例 |

说明：这个表格必须写成普通 Markdown，不要放进代码块，并且表格前后保留空行，这样 GitHub README 才会渲染成表格。

## 🧩 代码仓库筛选

```bash
PaperPilot "retrieval augmented generation" --auto-confirm --github-filter required
```

说明：

- `any`：保留全部论文，按有无代码进行标注
- `required`：仅保留检测到公开代码的论文（核心语料仍保存）
- `none`：仅保留未检测到公开代码的论文

## 🧪 常用参数

```text
--max-papers INT                 最终报告视图论文数量上限，默认 100
--min-report-papers INT          可选的正式报告最低论文数量，默认 0
--since-year INT                 起始年份
--github-filter any|required|none
--github-search-limit INT        GitHub 搜索数量上限
--no-download                    跳过 PDF 下载
--pdf-limit INT                  PDF 下载上限
--user-corpus PATH               本地语料路径，可重复传入
--mode quick|apa|systematic
--interaction auto|gated
--quality fast|balanced|strict
--include-adjacent               包含 adjacent 论文到矩阵与附录
--sources auto|all|core|biomed|cs|configured
--enable-source SOURCE           启用来源（可重复）
--disable-source SOURCE          禁用来源（可重复）
--no-obsidian-wiki               跳过 Obsidian Wiki 输出
```

## 🧱 开发与发布

### 预检

```bash
python -m unittest discover -s tests
python -m compileall literature_agent
python -m build
python -m twine check dist/*
```

### 发版建议

```bash
./publish_pypi.sh --dry-run --version <VERSION>
git add -A
git commit -m "chore: release v<VERSION>"
git tag -a v<VERSION> -m "v<VERSION>"
git push origin main --tags
./publish_pypi.sh --version <VERSION>
```

## 🌟 开源发布建议

- 切勿提交包含 token 的文件：`~/.paperpilot/config.json`、`api.json`、`llmapi.txt`、`.env`
- 建议先配置 `.gitignore`，避免上传运行目录/构建产物
- 保持 LICENSE 与文档同步更新
- 发布 Pages 时使用仓库设置：
  - `Settings` → `Pages`
  - `Build and deployment`
  - `Source: Deploy from a branch`
  - `Branch: main`
  - `Folder: /docs`

### 一键发布

```bash
# 仅预检（不上传）
./scripts/release_everywhere.sh --dry-run

# 完整发布（代码推送/打 tag/GitHub Release/PyPI）
export PYPI_TOKEN='pypi-...'
./scripts/release_everywhere.sh

# 不发布到 PyPI 的本地发版（如仅先推 GitHub）
./scripts/release_everywhere.sh --no-pypi
```

## 🙏 致谢与参考项目

PaperPilot 的设计参考了多个开源学术研究与 Agent 项目。感谢这些项目和作者公开高质量资料：

- [LLMForEverybody](https://github.com/luhengshiwo/LLMForEverybody)：Agent 设计范式与学习资料。
- [academic-research-skills](https://github.com/Imbad0202/academic-research-skills)：研究完整性、来源验证、结构化综合等思路。
- [DeepTutor](https://github.com/HKUDS/DeepTutor)：Tool/Capability 风格的 Agent 架构启发。
- [obsidian-wiki](https://github.com/ar9av/obsidian-wiki)：Obsidian Wiki 导出方向。
- [Research-Paper-Writing-Skills](https://github.com/Master-cai/Research-Paper-Writing-Skills)、[research-writing-skill](https://github.com/Norman-bury/research-writing-skill)、[SLR-FC](https://github.com/drshahizan/SLR-FC)：文献综述、科研写作和系统综述流程参考。

使用 PaperPilot 的场景中，建议在方法、输出和源码版本上给出明确版本号，保证复现。
