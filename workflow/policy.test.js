const test = require("node:test");
const assert = require("node:assert/strict");
const { priorityFor, triage, slaStatus } = require("./policy.js");

const T0 = "2026-09-14T09:00:00.000Z";
const minutesAfter = (iso, m) => new Date(new Date(iso).getTime() + m * 60000).toISOString();

test("priority matrix corners", () => {
  assert.equal(priorityFor("high", "high"), "P1");
  assert.equal(priorityFor("low", "low"), "P4");
  assert.equal(priorityFor("medium", "high"), "P2");
  assert.throws(() => priorityFor("huge", "high"));
});

test("P1 tooling outage pages on-call with a 15-minute SLA", () => {
  const t = triage({ category: "tooling_outage", impact: "high", urgency: "high", confidence: 0.95 }, T0);
  assert.equal(t.priority, "P1");
  assert.equal(t.team, "Tooling & IT");
  assert.equal(t.page_on_call, true);
  assert.equal(t.response_due_at, minutesAfter(T0, 15));
});

test("guideline question routes to Quality & Policy", () => {
  const t = triage({ category: "guideline_question", impact: "medium", urgency: "medium", confidence: 0.9 }, T0);
  assert.deepEqual([t.priority, t.team, t.page_on_call], ["P3", "Quality & Policy", false]);
});

test("unknown category falls back to ops triage", () => {
  const t = triage({ category: "something_new", impact: "low", urgency: "low", confidence: 0.9 }, T0);
  assert.equal(t.team, "Ops triage");
});

test("low confidence goes to a human and is never left at P4", () => {
  const t = triage({ category: "client_request", impact: "low", urgency: "low", confidence: 0.4 }, T0);
  assert.equal(t.needs_human_review, true);
  assert.equal(t.team, "Ops triage");
  assert.equal(t.priority, "P3");
});

test("low confidence never lowers a high priority", () => {
  const t = triage({ category: "tooling_outage", impact: "high", urgency: "high", confidence: 0.3 }, T0);
  assert.equal(t.priority, "P1");
});

test("SLA status moves on_track -> at_risk -> breached", () => {
  const ticket = { created_at: T0, response_due_at: minutesAfter(T0, 60) };
  assert.equal(slaStatus(ticket, minutesAfter(T0, 10)), "on_track");
  assert.equal(slaStatus(ticket, minutesAfter(T0, 46)), "at_risk");
  assert.equal(slaStatus(ticket, minutesAfter(T0, 61)), "breached");
});

test("responded tickets are met or breached_responded", () => {
  const due = minutesAfter(T0, 60);
  assert.equal(slaStatus({ created_at: T0, response_due_at: due, first_response_at: minutesAfter(T0, 30) }, minutesAfter(T0, 90)), "met");
  assert.equal(slaStatus({ created_at: T0, response_due_at: due, first_response_at: minutesAfter(T0, 75) }, minutesAfter(T0, 90)), "breached_responded");
});
