type PagesFunction<Env> = (context: {
  request: Request;
  env: Env;
}) => Response | Promise<Response>;

type Env = {
  LLM_API_KEY?: string;
  LLM_BASE_URL?: string;
  LLM_MODEL?: string;
  SEMANTIC_SCHOLAR_API_KEY?: string;
};

type SearchPlan = {
  research_question: string;
  search_queries: string[];
  inclusion_criteria: string[];
  exclusion_criteria: string[];
};

type LlmDiagnostic = {
  status: "configured" | "missing_key" | "http_error" | "invalid_response" | "request_error";
  httpStatus?: number;
  message?: string;
};

type Paper = {
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  abstract: string | null;
  url: string | null;
  doi: string | null;
  citationCount: number | null;
  source: string;
};

type ReportPayload = {
  markdown: string;
  html: string;
  filenameBase: string;
};

type SourceDiagnostic = {
  source: string;
  query: string;
  status: "ok" | "skipped" | "http_error" | "invalid_response" | "request_error";
  returned: number;
  httpStatus?: number;
  message?: string;
};

type SearchBatch = {
  papers: Paper[];
  diagnostic: SourceDiagnostic;
};

const DEFAULT_MODEL = "deepseek-v4-flash";
const DEFAULT_BASE_URL = "https://api.deepseek.com";
const API_KEY_PLACEHOLDERS = new Set(["", "123456", "changeme", "your-deepseek-key"]);

export const onRequestPost: PagesFunction<Env> = async ({ request, env }) => {
  let body: { query?: string; maxPapers?: number };
  try {
    body = await request.json();
  } catch {
    return json({ error: "Invalid JSON body" }, 400);
  }

  const query = String(body.query || "").trim();
  if (query.length < 8 || query.length > 1200) {
    return json({ error: "Query must be between 8 and 1200 characters." }, 400);
  }

  const maxPapers = Math.min(Math.max(Number(body.maxPapers || 10), 10), 50);
  const startedAt = Date.now();
  const llm: LlmDiagnostic = { status: "configured" };
  const plan = await buildSearchPlan(query, llm, env);
  if (!plan) {
    return json(
      {
        error: "LLM is temporarily unavailable. Please try again later.",
        diagnostics: { llm },
      },
      503,
    );
  }
  const searchQueries = normalizeQueries(plan.search_queries, query);
  const perSourceLimit = Math.min(10, Math.max(5, Math.ceil(maxPapers / Math.max(searchQueries.length, 1))));
  const batches = await searchScholarlySources(searchQueries, perSourceLimit, env);
  let sourceDiagnostics = batches.map((batch) => batch.diagnostic);
  let papers = rankPapers(dedupePapers(batches.flatMap((batch) => batch.papers))).slice(0, maxPapers);
  if (!papers.length) {
    const fallbackQueries = fallbackSearchQueries(query, plan, searchQueries);
    const fallbackBatches = await searchFallbackSources(fallbackQueries, maxPapers);
    sourceDiagnostics = sourceDiagnostics.concat(fallbackBatches.map((batch) => batch.diagnostic));
    papers = rankPapers(dedupePapers(fallbackBatches.flatMap((batch) => batch.papers))).slice(0, maxPapers);
  }
  const report = await buildReport(query, plan, papers, llm, env);
  if (!report) {
    return json(
      {
        error: "Report generation is temporarily unavailable. Please try again later.",
        diagnostics: { llm },
      },
      503,
    );
  }

  return json({
    query,
    plan: { ...plan, search_queries: searchQueries },
    papers,
    report,
    diagnostics: {
      sources: ["openalex", "crossref", "semantic_scholar"],
      llm,
      returned: papers.length,
      sourceDetails: sourceDiagnostics,
      elapsedMs: Date.now() - startedAt,
    },
    generatedAt: new Date().toISOString(),
  });
};

async function buildSearchPlan(query: string, diagnostic: LlmDiagnostic, env: Env): Promise<SearchPlan | null> {
  const apiKey = normalizeApiKey(env.LLM_API_KEY);
  const baseUrl = (env.LLM_BASE_URL || DEFAULT_BASE_URL).replace(/\/$/, "");
  const model = env.LLM_MODEL || DEFAULT_MODEL;
  if (!apiKey) {
    diagnostic.status = "missing_key";
    return null;
  }

  const prompt = [
    "You are PaperPilot's literature-search planning agent.",
    "Return strict JSON only, with this schema:",
    '{"research_question":"...","search_queries":["..."],"inclusion_criteria":["..."],"exclusion_criteria":["..."]}',
    "Create 3 concise English academic search queries for public scholarly APIs.",
    "Prefer concrete technical terms, venues, methods, tasks, and date constraints when present.",
    `User request: ${query}`,
  ].join("\n");

  try {
    const response = await fetch(`${baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        messages: [
          { role: "system", content: "Return JSON only. Do not wrap it in Markdown." },
          { role: "user", content: prompt },
        ],
        temperature: 0.2,
        max_tokens: 900,
      }),
    });
    if (!response.ok) {
      diagnostic.status = "http_error";
      diagnostic.httpStatus = response.status;
      return null;
    }
    const data: any = await response.json();
    const content = data?.choices?.[0]?.message?.content;
    const parsed = parsePlan(typeof content === "string" ? content : "");
    if (!parsed) {
      diagnostic.status = "invalid_response";
    }
    return parsed;
  } catch (error) {
    diagnostic.status = "request_error";
    diagnostic.message = error instanceof Error ? error.message.slice(0, 160) : "Unknown request error";
    return null;
  }
}

function parsePlan(content: string): SearchPlan | null {
  const match = content.match(/\{[\s\S]*\}/);
  if (!match) return null;
  try {
    const parsed = JSON.parse(match[0]);
    return {
      research_question: text(parsed.research_question),
      search_queries: arrayOfText(parsed.search_queries),
      inclusion_criteria: arrayOfText(parsed.inclusion_criteria),
      exclusion_criteria: arrayOfText(parsed.exclusion_criteria),
    };
  } catch {
    return null;
  }
}

function normalizeQueries(queries: string[], original: string): string[] {
  const clean = queries.map((item) => item.trim()).filter(Boolean);
  return [...new Set(clean.length ? clean : [original])].slice(0, 4);
}

function fallbackSearchQueries(original: string, plan: SearchPlan, usedQueries: string[]): string[] {
  const candidates = [
    plan.research_question,
    "retrieval augmented generation hallucination mitigation domain specific question answering",
    "knowledge grounded long context large language models factuality question answering",
    "LLM external knowledge bases retrieval augmented generation factual accuracy",
    original,
  ];
  const used = new Set(usedQueries.map((item) => item.toLowerCase()));
  return [...new Set(candidates.map((item) => item.trim()).filter(Boolean))]
    .filter((item) => !used.has(item.toLowerCase()))
    .slice(0, 4);
}

async function searchScholarlySources(queries: string[], limit: number, env: Env): Promise<SearchBatch[]> {
  const batches: SearchBatch[] = [];
  for (const query of queries) {
    batches.push(await searchOpenAlex(query, limit));
    await sleep(350);
  }
  if (!batches.some((batch) => batch.papers.length)) {
    for (const query of queries.slice(0, 2)) {
      batches.push(await searchCrossref(query, limit));
      await sleep(350);
    }
  }
  for (const query of queries.slice(0, 1)) {
    batches.push(await searchSemanticScholar(query, limit, env.SEMANTIC_SCHOLAR_API_KEY));
  }
  return batches;
}

async function searchFallbackSources(queries: string[], limit: number): Promise<SearchBatch[]> {
  const batches: SearchBatch[] = [];
  for (const query of queries) {
    batches.push(await searchCrossref(query, limit));
    await sleep(350);
  }
  return batches;
}

async function buildReport(
  query: string,
  plan: SearchPlan,
  papers: Paper[],
  diagnostic: LlmDiagnostic,
  env: Env,
): Promise<ReportPayload | null> {
  const summary = await buildReportSummary(query, plan, papers, diagnostic, env);
  if (!summary) return null;
  const generatedAt = new Date().toISOString();
  const filenameBase = `paperpilot-${slugify(plan.research_question || query, 48)}-${generatedAt.slice(0, 10)}`;
  const markdown = renderMarkdownReport(query, plan, papers, summary, generatedAt);
  const html = renderHtmlReport(query, plan, papers, summary, generatedAt);
  return { markdown, html, filenameBase };
}

async function buildReportSummary(
  query: string,
  plan: SearchPlan,
  papers: Paper[],
  diagnostic: LlmDiagnostic,
  env: Env,
): Promise<string | null> {
  const apiKey = normalizeApiKey(env.LLM_API_KEY);
  const baseUrl = (env.LLM_BASE_URL || DEFAULT_BASE_URL).replace(/\/$/, "");
  const model = env.LLM_MODEL || DEFAULT_MODEL;
  if (!apiKey) {
    diagnostic.status = "missing_key";
    return null;
  }
  const paperMetadata = papers.slice(0, 12).map((paper, index) => ({
    index: index + 1,
    title: paper.title,
    authors: paper.authors.slice(0, 6),
    year: paper.year,
    venue: paper.venue,
    abstract: paper.abstract ? paper.abstract.slice(0, 900) : null,
    citationCount: paper.citationCount,
    source: paper.source,
  }));
  const prompt = [
    "Write a concise Chinese literature-search briefing from the provided metadata.",
    "Return plain Markdown only, no fenced code.",
    "Include: 1) topic framing, 2) method/evaluation themes, 3) open-source/code availability caveat, 4) evidence limitations.",
    "Do not invent facts beyond titles, venues, years, abstracts, and citation metadata.",
    `Original user request: ${query}`,
    `Research question: ${plan.research_question}`,
    `Search queries: ${plan.search_queries.join(" | ")}`,
    `Papers JSON: ${JSON.stringify(paperMetadata)}`,
  ].join("\n");

  try {
    const response = await fetch(`${baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        messages: [
          { role: "system", content: "You write careful evidence-grounded research briefings." },
          { role: "user", content: prompt },
        ],
        temperature: 0.2,
        max_tokens: 1200,
      }),
    });
    if (!response.ok) {
      diagnostic.status = "http_error";
      diagnostic.httpStatus = response.status;
      return null;
    }
    const data: any = await response.json();
    const content = data?.choices?.[0]?.message?.content;
    if (typeof content !== "string" || !content.trim()) {
      diagnostic.status = "invalid_response";
      return null;
    }
    return content.trim();
  } catch (error) {
    diagnostic.status = "request_error";
    diagnostic.message = error instanceof Error ? error.message.slice(0, 160) : "Unknown request error";
    return null;
  }
}

function renderMarkdownReport(
  query: string,
  plan: SearchPlan,
  papers: Paper[],
  summary: string,
  generatedAt: string,
): string {
  const lines = [
    `# PaperPilot 轻量文献检索报告`,
    "",
    `生成时间：${generatedAt}`,
    "",
    `## 原始调研需求`,
    "",
    query,
    "",
    `## 研究问题`,
    "",
    plan.research_question,
    "",
    `## 检索式`,
    "",
    ...plan.search_queries.map((item) => `- ${item}`),
    "",
    `## 纳入标准`,
    "",
    ...plan.inclusion_criteria.map((item) => `- ${item}`),
    "",
    `## 排除标准`,
    "",
    ...plan.exclusion_criteria.map((item) => `- ${item}`),
    "",
    `## 主题摘要`,
    "",
    summary,
    "",
    `## 候选论文`,
    "",
    "| # | Title | Authors | Year | Venue | Source | Citations | Link |",
    "|---|---|---|---:|---|---|---:|---|",
    ...papers.map((paper, index) => {
      const link = paper.url ? `[Link](${paper.url})` : "";
      return [
        index + 1,
        escapeMarkdownTable(paper.title),
        escapeMarkdownTable(paper.authors.slice(0, 4).join(", ")),
        paper.year || "",
        escapeMarkdownTable(paper.venue || ""),
        escapeMarkdownTable(paper.source),
        paper.citationCount || 0,
        link,
      ].join(" | ");
    }).map((row) => `| ${row} |`),
    "",
    `## 局限性`,
    "",
    "- 该报告仅基于公开论文 API 返回的 metadata、abstract 和引用信息生成。",
    "- 未下载或解析全文 PDF，不等同于完整系统综述。",
    "- 代码开源情况需要进一步人工核验或使用完整 PaperPilot CLI workflow 检查。",
    "",
  ];
  return lines.join("\n");
}

function renderHtmlReport(
  query: string,
  plan: SearchPlan,
  papers: Paper[],
  summary: string,
  generatedAt: string,
): string {
  const paperRows = papers.map((paper, index) => `
    <tr>
      <td>${index + 1}</td>
      <td>${paper.url ? `<a href="${escapeAttribute(paper.url)}">${escapeHtml(paper.title)}</a>` : escapeHtml(paper.title)}</td>
      <td>${escapeHtml(paper.authors.slice(0, 4).join(", "))}</td>
      <td>${paper.year || ""}</td>
      <td>${escapeHtml(paper.venue || "")}</td>
      <td>${escapeHtml(paper.source)}</td>
      <td>${paper.citationCount || 0}</td>
    </tr>`).join("");
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PaperPilot 轻量文献检索报告</title>
  <style>
    body { font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.65; color: #0f172a; max-width: 1040px; margin: 0 auto; padding: 32px 20px; }
    h1, h2 { line-height: 1.2; }
    table { width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 14px; }
    th, td { border: 1px solid #dbe4ee; padding: 8px; vertical-align: top; }
    th { background: #f1f5f9; text-align: left; }
    a { color: #2563eb; }
    .summary { background: #f8fafc; border: 1px solid #dbe4ee; border-radius: 8px; padding: 16px; }
  </style>
</head>
<body>
  <h1>PaperPilot 轻量文献检索报告</h1>
  <p><strong>生成时间：</strong>${escapeHtml(generatedAt)}</p>
  <h2>原始调研需求</h2>
  <p>${escapeHtml(query)}</p>
  <h2>研究问题</h2>
  <p>${escapeHtml(plan.research_question)}</p>
  <h2>检索式</h2>
  <ul>${plan.search_queries.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
  <h2>纳入标准</h2>
  <ul>${plan.inclusion_criteria.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
  <h2>排除标准</h2>
  <ul>${plan.exclusion_criteria.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
  <h2>主题摘要</h2>
  <div class="summary">${markdownBlocksToHtml(summary)}</div>
  <h2>候选论文</h2>
  <table>
    <thead><tr><th>#</th><th>Title</th><th>Authors</th><th>Year</th><th>Venue</th><th>Source</th><th>Citations</th></tr></thead>
    <tbody>${paperRows}</tbody>
  </table>
  <h2>局限性</h2>
  <ul>
    <li>该报告仅基于公开论文 API 返回的 metadata、abstract 和引用信息生成。</li>
    <li>未下载或解析全文 PDF，不等同于完整系统综述。</li>
    <li>代码开源情况需要进一步人工核验或使用完整 PaperPilot CLI workflow 检查。</li>
  </ul>
</body>
</html>`;
}

async function searchSemanticScholar(query: string, limit: number, apiKey?: string): Promise<SearchBatch> {
  const params = new URLSearchParams({
    query,
    limit: String(limit),
    fields: "title,authors,year,abstract,venue,citationCount,externalIds,url",
  });
  const diagnostic: SourceDiagnostic = { source: "semantic_scholar", query, status: "ok", returned: 0 };
  if (!normalizeApiKey(apiKey)) {
    diagnostic.status = "skipped";
    diagnostic.message = "Semantic Scholar API key is not configured.";
    return { papers: [], diagnostic };
  }
  try {
    const response = await fetch(`https://api.semanticscholar.org/graph/v1/paper/search?${params}`, {
      headers: { Accept: "application/json", "x-api-key": normalizeApiKey(apiKey) || "" },
    });
    if (!response.ok) {
      diagnostic.status = "http_error";
      diagnostic.httpStatus = response.status;
      return { papers: [], diagnostic };
    }
    const data: any = await response.json();
    if (!Array.isArray(data?.data)) {
      diagnostic.status = "invalid_response";
      return { papers: [], diagnostic };
    }
    const papers = data.data
      ? data.data.map((item: any) => ({
          title: text(item.title),
          authors: Array.isArray(item.authors) ? item.authors.map((author: any) => text(author.name)).filter(Boolean) : [],
          year: numberOrNull(item.year),
          venue: textOrNull(item.venue),
          abstract: textOrNull(item.abstract),
          url: textOrNull(item.url),
          doi: textOrNull(item.externalIds?.DOI),
          citationCount: numberOrNull(item.citationCount),
          source: "semantic_scholar",
        })).filter((paper: Paper) => paper.title)
      : [];
    diagnostic.returned = papers.length;
    return { papers, diagnostic };
  } catch (error) {
    diagnostic.status = "request_error";
    diagnostic.message = error instanceof Error ? error.message.slice(0, 160) : "Unknown request error";
    return { papers: [], diagnostic };
  }
}

async function searchOpenAlex(query: string, limit: number): Promise<SearchBatch> {
  const params = new URLSearchParams({
    search: query,
    "per-page": String(limit),
    mailto: "haobin_chen@mail.dhu.edu.cn",
  });
  const diagnostic: SourceDiagnostic = { source: "openalex", query, status: "ok", returned: 0 };
  try {
    const response = await fetchWithRetry(`https://api.openalex.org/works?${params}`, {
      headers: {
        Accept: "application/json",
        "User-Agent": "PaperPilot/1.0 (https://github.com/CHB-learner/PaperPilot; mailto:haobin_chen@mail.dhu.edu.cn)",
      },
    });
    if (!response.ok) {
      diagnostic.status = "http_error";
      diagnostic.httpStatus = response.status;
      return { papers: [], diagnostic };
    }
    const data: any = await response.json();
    if (!Array.isArray(data?.results)) {
      diagnostic.status = "invalid_response";
      return { papers: [], diagnostic };
    }
    const papers = data.results
      ? data.results.map((item: any) => ({
          title: text(item.display_name || item.title),
          authors: Array.isArray(item.authorships)
            ? item.authorships.map((auth: any) => text(auth.author?.display_name)).filter(Boolean)
            : [],
          year: numberOrNull(item.publication_year),
          venue: textOrNull(item.primary_location?.source?.display_name),
          abstract: invertedAbstract(item.abstract_inverted_index),
          url: textOrNull(item.doi || item.id),
          doi: normalizeDoi(item.doi),
          citationCount: numberOrNull(item.cited_by_count),
          source: "openalex",
        })).filter((paper: Paper) => paper.title)
      : [];
    diagnostic.returned = papers.length;
    return { papers, diagnostic };
  } catch (error) {
    diagnostic.status = "request_error";
    diagnostic.message = error instanceof Error ? error.message.slice(0, 160) : "Unknown request error";
    return { papers: [], diagnostic };
  }
}

async function searchCrossref(query: string, limit: number): Promise<SearchBatch> {
  const params = new URLSearchParams({
    query,
    rows: String(limit),
    mailto: "haobin_chen@mail.dhu.edu.cn",
  });
  const diagnostic: SourceDiagnostic = { source: "crossref", query, status: "ok", returned: 0 };
  try {
    const response = await fetchWithRetry(`https://api.crossref.org/works?${params}`, {
      headers: {
        Accept: "application/json",
        "User-Agent": "PaperPilot/1.0 (https://github.com/CHB-learner/PaperPilot; mailto:haobin_chen@mail.dhu.edu.cn)",
      },
    });
    if (!response.ok) {
      diagnostic.status = "http_error";
      diagnostic.httpStatus = response.status;
      return { papers: [], diagnostic };
    }
    const data: any = await response.json();
    const items = data?.message?.items;
    if (!Array.isArray(items)) {
      diagnostic.status = "invalid_response";
      return { papers: [], diagnostic };
    }
    const papers = items.map((item: any) => {
      const dateParts = item.published?.["date-parts"] || item["published-print"]?.["date-parts"] || item["published-online"]?.["date-parts"];
      return {
        title: text(Array.isArray(item.title) ? item.title[0] : item.title),
        authors: Array.isArray(item.author)
          ? item.author.map((author: any) => [text(author.given), text(author.family)].filter(Boolean).join(" ")).filter(Boolean)
          : [],
        year: Array.isArray(dateParts?.[0]) ? numberOrNull(dateParts[0][0]) : null,
        venue: textOrNull(Array.isArray(item["container-title"]) ? item["container-title"][0] : item["container-title"]),
        abstract: textOrNull(item.abstract),
        url: textOrNull(item.URL || (item.DOI ? `https://doi.org/${item.DOI}` : "")),
        doi: normalizeDoi(item.DOI),
        citationCount: numberOrNull(item["is-referenced-by-count"]),
        source: "crossref",
      };
    }).filter((paper: Paper) => paper.title);
    diagnostic.returned = papers.length;
    return { papers, diagnostic };
  } catch (error) {
    diagnostic.status = "request_error";
    diagnostic.message = error instanceof Error ? error.message.slice(0, 160) : "Unknown request error";
    return { papers: [], diagnostic };
  }
}

async function fetchWithRetry(input: string, init: RequestInit): Promise<Response> {
  let response = await fetch(input, init);
  if (response.status !== 429) return response;
  await sleep(900);
  response = await fetch(input, init);
  if (response.status !== 429) return response;
  await sleep(1800);
  return fetch(input, init);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function dedupePapers(papers: Paper[]): Paper[] {
  const seen = new Set<string>();
  const result: Paper[] = [];
  for (const paper of papers) {
    const key = (paper.doi || paper.url || paper.title).toLowerCase().replace(/\W+/g, "");
    if (!key || seen.has(key)) continue;
    seen.add(key);
    result.push(paper);
  }
  return result;
}

function rankPapers(papers: Paper[]): Paper[] {
  return papers.sort((a, b) => {
    const citations = (b.citationCount || 0) - (a.citationCount || 0);
    if (citations !== 0) return citations;
    return (b.year || 0) - (a.year || 0);
  });
}

function invertedAbstract(index: Record<string, number[]> | null | undefined): string | null {
  if (!index || typeof index !== "object") return null;
  const words: string[] = [];
  for (const [word, positions] of Object.entries(index)) {
    for (const position of positions || []) {
      words[position] = word;
    }
  }
  return words.filter(Boolean).join(" ") || null;
}

function normalizeDoi(value: unknown): string | null {
  const doi = text(value).replace(/^https?:\/\/doi\.org\//i, "");
  return doi || null;
}

function arrayOfText(value: unknown): string[] {
  return Array.isArray(value) ? value.map(text).filter(Boolean) : [];
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function textOrNull(value: unknown): string | null {
  const clean = text(value);
  return clean || null;
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function normalizeApiKey(value: string | undefined): string | undefined {
  const clean = (value || "").trim();
  return API_KEY_PLACEHOLDERS.has(clean.toLowerCase()) ? undefined : clean;
}

function slugify(value: string, maxLength: number): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, maxLength)
    .replace(/-+$/g, "");
  return slug || "literature-report";
}

function escapeMarkdownTable(value: string): string {
  return value.replace(/\|/g, "\\|").replace(/\n+/g, " ").trim();
}

function markdownBlocksToHtml(markdown: string): string {
  return markdown
    .split(/\n{2,}/)
    .map((block) => {
      const trimmed = block.trim();
      if (!trimmed) return "";
      if (trimmed.startsWith("- ")) {
        const items = trimmed
          .split("\n")
          .map((line) => line.replace(/^- /, "").trim())
          .filter(Boolean)
          .map((line) => `<li>${escapeHtml(line)}</li>`)
          .join("");
        return `<ul>${items}</ul>`;
      }
      return `<p>${escapeHtml(trimmed).replace(/\n/g, "<br>")}</p>`;
    })
    .join("\n");
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char] || char));
}

function escapeAttribute(value: string): string {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}
