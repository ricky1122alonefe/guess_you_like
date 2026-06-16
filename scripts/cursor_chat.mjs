import { Agent } from "@cursor/sdk";

let raw = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) {
  raw += chunk;
}

const payload = JSON.parse(raw || "{}");
const messages = payload.messages || [];
const prompt = [
  ...messages.map((m) => `[${m.role || "user"}]\n${m.content || ""}`),
  "只返回符合要求的纯 JSON，不要 markdown 代码块。"
].join("\n\n");

try {
  const result = await Agent.prompt(prompt, {
    apiKey: payload.apiKey || process.env.CURSOR_API_KEY,
    model: { id: payload.model || process.env.CURSOR_MODEL || "composer-2.5-fast" },
    local: { cwd: payload.cwd || process.cwd() }
  });

  const text = typeof result.result === "string"
    ? result.result
    : JSON.stringify(result.result ?? "");

  if (result.status && !["finished", "completed", "success"].includes(result.status)) {
    console.error(JSON.stringify({ ok: false, status: result.status, error: text }));
    process.exit(2);
  }

  process.stdout.write(JSON.stringify({ ok: true, text }));
} catch (err) {
  process.stderr.write(JSON.stringify({
    ok: false,
    error: err?.message || String(err),
    name: err?.name || "Error"
  }));
  process.exit(1);
}
