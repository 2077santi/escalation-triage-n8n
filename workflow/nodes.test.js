// Runs the Code nodes from the generated n8n workflows with mocked n8n inputs,
// so the exported JSON is tested, not just the source files.
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const load = file => require(path.join(__dirname, "..", "n8n", file));
const codeOf = (wf, name) => wf.nodes.find(n => n.name === name).parameters.jsCode;

function runCode(code, inputItems, nodeOutputs = {}) {
  const $input = { first: () => inputItems[0], all: () => inputItems };
  const $ = name => ({ first: () => nodeOutputs[name][0], item: nodeOutputs[name][0] });
  return new Function("$input", "$", code)($input, $);
}

const triageWf = load("escalation-triage.json");

test("Prepare request builds a structured-output Claude request", () => {
  const [out] = runCode(codeOf(triageWf, "Prepare request"),
    [{ json: { body: { reporter: "Team lead", text: "Tool down for everyone" } } }]);
  const { ticket, request } = out.json;
  assert.match(ticket.ticket_id, /^ESC-/);
  assert.equal(request.model, "claude-opus-5-5");
  assert.equal(request.output_config.format.type, "json_schema");
  assert.match(request.messages[0].content, /<issue>\nTool down for everyone\n<\/issue>/);
});

test("Apply policy turns a Claude response into a routed P1", () => {
  const ticket = { ticket_id: "ESC-1", created_at: "2026-09-14T09:00:00.000Z", reporter: "TL", text: "Tool down" };
  const claude = { stop_reason: "end_turn", content: [{ type: "text", text: JSON.stringify({
    category: "tooling_outage", impact: "high", urgency: "high", summary: "Tool down", confidence: 0.93, reasoning: "Team blocked" }) }] };
  const [out] = runCode(codeOf(triageWf, "Apply policy"), [{ json: claude }], { "Prepare request": [{ json: { ticket } }] });
  assert.equal(out.json.priority, "P1");
  assert.equal(out.json.channel, "#ops-tooling");
  assert.equal(out.json.page_on_call, true);
  assert.equal(out.json.response_due_at, "2026-09-14T09:15:00.000Z");
});

test("Apply policy fails safe when Claude is unavailable", () => {
  const ticket = { ticket_id: "ESC-2", created_at: "2026-09-14T09:00:00.000Z", reporter: "A", text: "something broke" };
  const [out] = runCode(codeOf(triageWf, "Apply policy"), [{ json: { error: { message: "timeout" } } }], { "Prepare request": [{ json: { ticket } }] });
  assert.equal(out.json.needs_human_review, true);
  assert.equal(out.json.team, "Ops triage");
});

test("Watchdog alerts once per status change", () => {
  const wf = load("sla-watchdog.json");
  const old = new Date(Date.now() - 2 * 3600e3).toISOString();
  const due = new Date(Date.now() - 3600e3).toISOString();
  const rows = [
    { json: { ticket_id: "A", created_at: old, response_due_at: due, status: "open", last_alert: "" } },          // breached, not yet alerted
    { json: { ticket_id: "B", created_at: old, response_due_at: due, status: "open", last_alert: "breached" } },  // already alerted
    { json: { ticket_id: "C", created_at: old, response_due_at: due, status: "closed", last_alert: "" } },        // closed
  ];
  const alerts = runCode(codeOf(wf, "Check SLA"), rows);
  assert.deepEqual(alerts.map(a => [a.json.ticket_id, a.json.sla_status]), [["A", "breached"]]);
});
