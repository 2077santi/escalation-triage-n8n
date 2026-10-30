// Escalation policy: priority matrix, SLA timers, routing and breach detection.
// This file is embedded verbatim into the n8n Code nodes by build.py, and
// unit-tested with `node --test`, so the tested logic is the deployed logic.

const PRIORITY_MATRIX = {
  // impact -> urgency -> priority (ITIL-style)
  high: { high: "P1", medium: "P2", low: "P3" },
  medium: { high: "P2", medium: "P3", low: "P3" },
  low: { high: "P3", medium: "P4", low: "P4" },
};

// Minutes to first response, by priority.
const SLA_MINUTES = { P1: 15, P2: 60, P3: 240, P4: 1440 };

const ROUTING = {
  tooling_outage: { team: "Tooling & IT", channel: "#ops-tooling" },
  access_issue: { team: "IT support", channel: "#it-support" },
  guideline_question: { team: "Quality & Policy", channel: "#quality-policy" },
  data_quality: { team: "Quality & Policy", channel: "#quality-policy" },
  capacity_risk: { team: "Delivery lead", channel: "#delivery" },
  client_request: { team: "Project management", channel: "#project-mgmt" },
  other: { team: "Ops triage", channel: "#ops-triage" },
};

const MIN_CONFIDENCE = 0.6;
const AT_RISK_SHARE = 0.75; // warn when 75% of the SLA has elapsed without a response

function priorityFor(impact, urgency) {
  const row = PRIORITY_MATRIX[impact];
  if (!row || !row[urgency]) throw new Error(`unknown impact/urgency: ${impact}/${urgency}`);
  return row[urgency];
}

function triage(classification, createdAt) {
  const { category, impact, urgency, confidence } = classification;
  const lowConfidence = typeof confidence !== "number" || confidence < MIN_CONFIDENCE;
  let priority = priorityFor(impact, urgency);
  // A human looks at anything the model is unsure about, and unsure tickets are never left at P4.
  if (lowConfidence && (priority === "P4" || priority === "P3")) priority = "P3";
  const route = lowConfidence ? ROUTING.other : (ROUTING[category] || ROUTING.other);
  const created = new Date(createdAt);
  const due = new Date(created.getTime() + SLA_MINUTES[priority] * 60000);
  return {
    priority,
    team: route.team,
    channel: route.channel,
    sla_minutes: SLA_MINUTES[priority],
    response_due_at: due.toISOString(),
    page_on_call: priority === "P1",
    needs_human_review: lowConfidence,
  };
}

function slaStatus(ticket, now) {
  const created = new Date(ticket.created_at).getTime();
  const due = new Date(ticket.response_due_at).getTime();
  const nowMs = new Date(now).getTime();
  if (ticket.first_response_at) {
    return new Date(ticket.first_response_at).getTime() <= due ? "met" : "breached_responded";
  }
  if (nowMs > due) return "breached";
  if ((nowMs - created) / (due - created) >= AT_RISK_SHARE) return "at_risk";
  return "on_track";
}

if (typeof module !== "undefined") {
  module.exports = { PRIORITY_MATRIX, SLA_MINUTES, ROUTING, MIN_CONFIDENCE, priorityFor, triage, slaStatus };
}
