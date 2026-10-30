"""Generate the importable n8n workflows from policy.js and classifier.json.

Run: python workflow/build.py
Writes n8n/escalation-triage.json and n8n/sla-watchdog.json, embedding the
tested policy.js in the Code nodes so the deployed logic is the tested logic.
"""

import json
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "n8n"
POLICY = (HERE / "policy.js").read_text()
CLASSIFIER = json.loads((HERE / "classifier.json").read_text())
SHEET_ID = "REPLACE_WITH_YOUR_GOOGLE_SHEET_ID"


def node(name, type_, version, position, parameters, **extra):
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, name)), "name": name, "type": type_, "typeVersion": version,
            "position": position, "parameters": parameters, **extra}


def chain(*names):
    """n8n 'connections' for a straight line of nodes."""
    return {a: {"main": [[{"node": b, "type": "main", "index": 0}]]} for a, b in zip(names, names[1:])}


PREPARE_JS = f"""// Build the Claude request for this ticket.
const CLASSIFIER = {json.dumps(CLASSIFIER)};
const body = $input.first().json.body ?? $input.first().json;
const ticket = {{
  ticket_id: 'ESC-' + Date.now().toString(36).toUpperCase(),
  created_at: new Date().toISOString(),
  reporter: String(body.reporter ?? 'unknown').slice(0, 200),
  text: String(body.text ?? '').slice(0, 4000),
}};
const request = {{
  model: CLASSIFIER.model,
  max_tokens: 2000,
  fallbacks: 'default',
  output_config: {{ format: {{ type: 'json_schema', schema: CLASSIFIER.schema }} }},
  messages: [{{ role: 'user', content: CLASSIFIER.instructions + '\\n\\n<reporter>' + ticket.reporter + '</reporter>\\n<issue>\\n' + ticket.text + '\\n</issue>' }}],
}};
return [{{ json: {{ ticket, request }} }}];"""

APPLY_JS = f"""{POLICY}

// Parse Claude's structured output; if anything is off, fail safe to human triage.
const ticket = $('Prepare request').first().json.ticket;
const response = $input.first().json;
let classification;
try {{
  if (response.stop_reason === 'refusal') throw new Error('refused');
  const text = (response.content || []).find(b => b.type === 'text').text;
  classification = JSON.parse(text);
}} catch (e) {{
  classification = {{ category: 'other', impact: 'medium', urgency: 'medium', confidence: 0,
    summary: ticket.text.slice(0, 80), reasoning: 'Classifier unavailable (' + e.message + '); sent to human triage.' }};
}}
const decision = triage(classification, ticket.created_at);
return [{{ json: {{ ...ticket, ...classification, ...decision, status: 'open', first_response_at: '', last_alert: '' }} }}];"""

WATCHDOG_JS = f"""{POLICY}

// Alert once per status change: on_track -> at_risk -> breached.
const now = new Date().toISOString();
const alerts = [];
for (const item of $input.all()) {{
  const t = item.json;
  if (!t.ticket_id || t.status === 'closed') continue;
  const status = slaStatus({{ ...t, first_response_at: t.first_response_at || null }}, now);
  if ((status === 'at_risk' || status === 'breached') && t.last_alert !== status) {{
    alerts.push({{ json: {{ ticket_id: t.ticket_id, last_alert: status, priority: t.priority, team: t.team,
      channel: t.channel, summary: t.summary, response_due_at: t.response_due_at, sla_status: status }} }});
  }}
}}
return alerts;"""


def sheet(name, operation, position, extra=None):
    params = {"operation": operation, "documentId": {"__rl": True, "value": SHEET_ID, "mode": "id"},
              "sheetName": {"__rl": True, "value": "Queue", "mode": "name"}, **(extra or {})}
    return node(name, "n8n-nodes-base.googleSheets", 4.5, position, params)


def slack(name, channel_expr, text, position):
    return node(name, "n8n-nodes-base.slack", 2.2, position, {
        "select": "channel", "channelId": {"__rl": True, "value": channel_expr, "mode": "name"}, "text": text, "otherOptions": {}})


def triage_workflow():
    nodes = [
        node("Webhook", "n8n-nodes-base.webhook", 2, [0, 300],
             {"httpMethod": "POST", "path": "escalation", "responseMode": "responseNode", "options": {}}),
        node("Prepare request", "n8n-nodes-base.code", 2, [220, 300], {"jsCode": PREPARE_JS}),
        node("Classify with Claude", "n8n-nodes-base.httpRequest", 4.2, [440, 300], {
            "method": "POST", "url": "https://api.anthropic.com/v1/messages",
            "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
            "sendHeaders": True, "headerParameters": {"parameters": [
                {"name": "anthropic-version", "value": "2023-06-01"},
                {"name": "anthropic-beta", "value": "server-side-fallback-2026-07-01"}]},
            "sendBody": True, "specifyBody": "json", "jsonBody": "={{ JSON.stringify($json.request) }}",
            "options": {"timeout": 60000}}, retryOnFail=True, maxTries=3, onError="continueRegularOutput"),
        node("Apply policy", "n8n-nodes-base.code", 2, [660, 300], {"jsCode": APPLY_JS}),
        node("Respond", "n8n-nodes-base.respondToWebhook", 1.1, [880, 120], {
            "respondWith": "json", "responseBody": "={{ { ticket_id: $json.ticket_id, priority: $json.priority, team: $json.team, response_due_at: $json.response_due_at } }}", "options": {}}),
        sheet("Log to queue", "append", [880, 300], {"columns": {"mappingMode": "autoMapInputData", "value": {}}, "options": {}}),
        slack("Notify team", "={{ $json.channel }}",
              "=*{{ $json.priority }}* {{ $json.summary }}\n{{ $json.reasoning }}\nTicket {{ $json.ticket_id }} - respond by {{ $json.response_due_at }}"
              "{{ $json.needs_human_review ? '\\n:warning: low classifier confidence - please re-triage' : '' }}", [1100, 300]),
        node("P1?", "n8n-nodes-base.if", 2, [1320, 300], {
            "conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict"},
                           "conditions": [{"id": "p1", "leftValue": "={{ $json.page_on_call }}", "rightValue": True,
                                           "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
                           "combinator": "and"}, "options": {}}),
        slack("Page on-call", "#ops-oncall",
              "=<!here> P1 escalation for {{ $json.team }}: {{ $json.summary }}\nTicket {{ $json.ticket_id }} - first response due in 15 min.", [1540, 220]),
    ]
    connections = chain("Webhook", "Prepare request", "Classify with Claude", "Apply policy", "Log to queue", "Notify team", "P1?")
    connections["Apply policy"]["main"][0].append({"node": "Respond", "type": "main", "index": 0})
    connections["P1?"] = {"main": [[{"node": "Page on-call", "type": "main", "index": 0}], []]}
    return {"name": "Escalation triage (Claude + SLA policy)", "nodes": nodes, "connections": connections,
            "settings": {"executionOrder": "v1"}, "active": False}


def watchdog_workflow():
    nodes = [
        node("Every 15 minutes", "n8n-nodes-base.scheduleTrigger", 1.2, [0, 300],
             {"rule": {"interval": [{"field": "minutes", "minutesInterval": 15}]}}),
        sheet("Read open tickets", "read", [220, 300], {"options": {}}),
        node("Check SLA", "n8n-nodes-base.code", 2, [440, 300], {"jsCode": WATCHDOG_JS}),
        sheet("Mark alerted", "update", [660, 300], {
            "columns": {"mappingMode": "autoMapInputData", "value": {}, "matchingColumns": ["ticket_id"]}, "options": {}}),
        slack("Alert team", "={{ $('Check SLA').item.json.channel }}",
              "={{ $('Check SLA').item.json.sla_status === 'breached' ? ':red_circle: SLA BREACHED' : ':large_orange_circle: SLA at risk' }} "
              "- {{ $('Check SLA').item.json.priority }} {{ $('Check SLA').item.json.ticket_id }}: {{ $('Check SLA').item.json.summary }} "
              "(due {{ $('Check SLA').item.json.response_due_at }})", [880, 300]),
    ]
    return {"name": "SLA watchdog", "nodes": nodes,
            "connections": chain("Every 15 minutes", "Read open tickets", "Check SLA", "Mark alerted", "Alert team"),
            "settings": {"executionOrder": "v1"}, "active": False}


def validate(workflow):
    names = {n["name"] for n in workflow["nodes"]}
    assert len(names) == len(workflow["nodes"]), "duplicate node names"
    for source, outputs in workflow["connections"].items():
        assert source in names, f"unknown source {source}"
        for branch in outputs["main"]:
            for link in branch:
                assert link["node"] in names, f"{source} -> unknown {link['node']}"


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for filename, wf in [("escalation-triage.json", triage_workflow()), ("sla-watchdog.json", watchdog_workflow())]:
        validate(wf)
        (OUT / filename).write_text(json.dumps(wf, indent=2) + "\n")
        print(f"wrote n8n/{filename} ({len(wf['nodes'])} nodes)")
