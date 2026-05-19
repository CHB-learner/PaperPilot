# ScholarFlow Vault Example

This page shows a sanitized example vault layout for public documentation. All names, topics, paths, and paper titles below are fabricated examples.

## Example Layout

```text
{vault}/
├── DailyPapers/
│   └── 2026/
│       └── 05/
│           └── 2026-05-20-paper-recommendations.md
│
├── Research_Fields/
│   └── GraphRAG/
│       ├── summary.md
│       ├── _meta/
│       │   ├── candidates.json
│       │   ├── screening.json
│       │   ├── source_diagnostics.json
│       │   ├── dedup_stats.json
│       │   └── topic_papers.json
│       └── papers/
│           └── CitationGraph-RAG/
│               ├── CitationGraph-RAG_en.md
│               ├── CitationGraph-RAG_zh.md
│               ├── CitationGraph-RAG.pdf
│               └── pngs/
│
├── Research_Fields/
│   └── ScientificAgents/
│       ├── summary.md
│       ├── _meta/
│       │   ├── candidates.json
│       │   ├── screening.json
│       │   ├── source_diagnostics.json
│       │   ├── dedup_stats.json
│       │   └── topic_papers.json
│       └── papers/
│           └── BenchAgent-Eval/
│               ├── BenchAgent-Eval_en.md
│               ├── BenchAgent-Eval_zh.md
│               ├── BenchAgent-Eval.pdf
│               └── pngs/
│
└── Uncategorized/
    ├── summary.md
    └── papers/
        └── LatentReview-Miner/
            ├── LatentReview-Miner_en.md
            ├── LatentReview-Miner_zh.md
            ├── LatentReview-Miner.pdf
            └── pngs/
```

## Example Config

Use placeholders or environment variables for local paths. Do not commit personal filesystem paths, private vault names, Zotero profile paths, API keys, or signed URLs.

```json
{
  "vault": "${SCHOLARFLOW_VAULT_PATH}",
  "folders": {
    "daily": "DailyPapers",
    "research": "Research_Fields",
    "uncategorized": "Uncategorized"
  },
  "daily": {
    "keywords": [
      "graph retrieval",
      "scientific agents"
    ]
  },
  "fields": {
    "GraphRAG": [
      "graph retrieval augmented generation",
      "citation graph reasoning",
      "knowledge graph RAG"
    ],
    "ScientificAgents": [
      "scientific discovery agent",
      "LLM research assistant",
      "tool-using agent evaluation"
    ]
  },
  "zotero": {
    "db": "${ZOTERO_DB_PATH}",
    "storage": "${ZOTERO_STORAGE_PATH}"
  }
}
```

The same JSON is available as [`examples/scholarflow.example.json`](../examples/scholarflow.example.json).

## Example `summary.md` Table

The field-level `summary.md` page can maintain a compact auto-index table. Keep it as plain Markdown, not a fenced code block, so GitHub and Obsidian can render it as a table.

| Date | Paper | Notes | Code | Source | Remarks |
|---|---|---|---|---|---|
| 2026.05.20 | [CitationGraph-RAG](https://example.org/papers/citationgraph-rag) | To read | [GitHub](https://github.com/example/citationgraph-rag) | [arXiv](https://arxiv.org/) | Public demo row |
| 2026.05.18 | [BenchAgent-Eval](https://example.org/papers/benchagent-eval) | Draft note |  | [OpenReview](https://openreview.net/) | Sanitized example |

Chinese-column variant:

| 发布时间 | 论文 | 笔记 | 代码 | 来源 | 备注 |
|---|---|---|---|---|---|
| 2026.05.20 | [CitationGraph-RAG](https://example.org/papers/citationgraph-rag) | 待精读 | [GitHub](https://github.com/example/citationgraph-rag) | [arXiv](https://arxiv.org/) | 公开演示行 |
| 2026.05.18 | [BenchAgent-Eval](https://example.org/papers/benchagent-eval) | 草稿笔记 |  | [OpenReview](https://openreview.net/) | 脱敏示例 |
