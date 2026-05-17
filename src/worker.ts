import { onRequestPost } from "../functions/api/literature-search";
import demoHtml from "../docs/demo.html";

type Env = {
  ASSETS: Fetcher;
  LLM_API_KEY?: string;
  LLM_BASE_URL?: string;
  LLM_MODEL?: string;
};

function html(content: string): Response {
  return new Response(content, {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
    },
  });
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}

export default {
  async fetch(request, env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/api/literature-search") {
      if (request.method !== "POST") {
        return json({ error: "Method not allowed" }, 405);
      }
      return onRequestPost({ request, env });
    }

    if (url.pathname === "/" || url.pathname === "/demo") {
      return html(demoHtml);
    }

    return env.ASSETS.fetch(request);
  },
} satisfies ExportedHandler<Env>;
