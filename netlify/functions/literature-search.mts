import type { Config, Context } from "@netlify/functions";

declare const Netlify: {
  env: {
    get(name: string): string | undefined;
  };
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

const DEFAULT_MODEL = "deepseek-v4-flash-ascend";
const DEFAULT_BASE_URL = "https://api.llm.ustc.edu.cn/v1";

export default async (req: Request, _context: Context) => {
  if (req.method !== "POST") {
    return json({ error: "Method not allowed" }, 405);
  }

  let body: { query?: string; maxPapers?: number };
  try {
    body = await req.json();
  } catch {
    return json({ error: "Invalid JSON body" }, 400);
  }

  const query = String(body.query || "").trim();
  if (query.length < 8 || query.length > 1200) {
    return json({ error: "Query must be between 8 and 1200 characters." }, 400);
  }

  const maxPapers = Math.min(Math.max(Number(body.maxPapers || 12), 5), 24);
  const startedAt = Date.now();
  const llm: LlmDiagnostic = { status: "configured" };
  const plan = await buildSearchPlan(query, llm);
  const searchQueries = normalizeQueries(plan.search_queries, query);
  const batches = await Promise.all(
    searchQueries.flatMap((searchQuery) => [
      searchSemanticScholar(searchQuery, 8),
      searchOpenAlex(searchQuery, 8),
    ]),
  );
  const papers = rankPapers(dedupePapers(batches.flat())).slice(0, maxPapers);

  return json({
    query,
    plan: { ...plan, search_queries: searchQueries },
    papers,
    diagnostics: {
      sources: ["semantic_scholar", "openalex"],
      llm,
      returned: papers.length,
      elapsedMs: Date.now() - startedAt,
    },
    generatedAt: new Date().toISOString(),
  });
};

export const config: Config = {
  path: "/api/literature-search",
};

async function buildSearchPlan(query: string, diagnostic: LlmDiagnostic): Promise<SearchPlan> {
  const apiKey = env("LLM_API_KEY");
  const baseUrl = (env("LLM_BASE_URL") || DEFAULT_BASE_URL).replace(/\/$/, "");
  const model = env("LLM_MODEL") || DEFAULT_MODEL;
  if (!apiKey) {
    diagnostic.status = "missing_key";
    return fallbackPlan(query);
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
      return fallbackPlan(query);
    }
    const data = await response.json();
    const content = data?.choices?.[0]?.message?.content;
    const parsed = parsePlan(typeof content === "string" ? content : "");
    if (!parsed) {
      diagnostic.status = "invalid_response";
    }
    return parsed || fallbackPlan(query);
  } catch (error) {
    diagnostic.status = "request_error";
    diagnostic.message = error instanceof Error ? error.message.slice(0, 160) : "Unknown request error";
    return fallbackPlan(query);
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

function fallbackPlan(query: string): SearchPlan {
  return {
    research_question: query,
    search_queries: [query],
    inclusion_criteria: ["Relevant scholarly papers", "Clear method or empirical evidence"],
    exclusion_criteria: ["Unrelated application domains", "Non-scholarly pages"],
  };
}

function normalizeQueries(queries: string[], original: string): string[] {
  const clean = queries.map((item) => item.trim()).filter(Boolean);
  return [...new Set(clean.length ? clean : [original])].slice(0, 4);
}

async function searchSemanticScholar(query: string, limit: number): Promise<Paper[]> {
  const params = new URLSearchParams({
    query,
    limit: String(limit),
    fields: "title,authors,year,abstract,venue,citationCount,externalIds,url",
  });
  try {
    const response = await fetch(`https://api.semanticscholar.org/graph/v1/paper/search?${params}`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return [];
    const data = await response.json();
    return Array.isArray(data?.data)
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
  } catch {
    return [];
  }
}

async function searchOpenAlex(query: string, limit: number): Promise<Paper[]> {
  const params = new URLSearchParams({ search: query, "per-page": String(limit) });
  try {
    const response = await fetch(`https://api.openalex.org/works?${params}`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return [];
    const data = await response.json();
    return Array.isArray(data?.results)
      ? data.results.map((item: any) => ({
          title: text(item.display_name),
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
  } catch {
    return [];
  }
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

function env(name: string): string | undefined {
  return Netlify.env.get(name) || process.env[name];
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}
