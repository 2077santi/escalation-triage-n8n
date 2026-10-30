# Spec - Escalation Triage Automation

## Context

Escalations in an AI data program arrive unstructured through several channels. Triage is manual, so response time depends on who happens to read the message first. Goal: every escalation is classified, prioritized, routed and timed within seconds, with humans kept in the loop where the system is unsure.

## Users

- **Reporter** (annotator, team lead, PM): submits an issue, gets a ticket id and a response deadline.
- **Owning team** (Tooling & IT, Quality & Policy, Delivery, PM, IT support): receives routed tickets.
- **On-call ops lead**: is paged for P1s.
- **Ops manager**: owns the policy (matrix, SLAs, routing).

## Requirements (EARS format)

### Intake and classification

- **R1.** When an escalation is submitted, the system shall return a ticket id, priority, owning team and response deadline to the reporter.
- **R2.** The system shall classify each escalation into category, impact and urgency using a fixed JSON schema, and shall not let the model set priority, SLA or routing directly.
- **R3.** If classification fails (timeout, error, refusal or invalid output), then the system shall log the ticket and route it to Ops triage for human review.
- **R4.** If classifier confidence is below 0.6, then the system shall route the ticket to Ops triage, flag it for review, and set its priority to at least P3.

### Policy

- **R5.** The system shall derive priority from the impact × urgency matrix in `policy.js`.
- **R6.** The system shall set the first-response deadline from priority: P1 15 min, P2 60 min, P3 4 h, P4 24 h.
- **R7.** When a ticket is P1, the system shall page the on-call channel in addition to notifying the owning team.

### SLA monitoring

- **R8.** Every 15 minutes, the system shall check open tickets without a first response.
- **R9.** When 75% of a ticket's SLA has elapsed without a response, the system shall alert the owning team that the ticket is at risk; when the deadline passes, it shall alert that the SLA is breached.
- **R10.** The system shall alert at most once per ticket per status.

### Quality

- **R11.** Before each prompt or policy change goes live, the classifier shall be evaluated on the golden set, reporting accuracy per field, under-prioritized tickets and missed P1s. A change that misses any P1 shall not be deployed.

## Acceptance tests

| Req | Test |
|---|---|
| R1, R2 | `Prepare request builds a structured-output Claude request`, `Apply policy turns a Claude response into a routed P1` |
| R3 | `Apply policy fails safe when Claude is unavailable` |
| R4 | `low confidence goes to a human and is never left at P4`, `low confidence never lowers a high priority` |
| R5, R6, R7 | `priority matrix corners`, `P1 tooling outage pages on-call with a 15-minute SLA` |
| R9 | `SLA status moves on_track -> at_risk -> breached` |
| R10 | `Watchdog alerts once per status change` |
| R11 | `eval/evaluate.py` (`missed_p1` must be empty) |

## Out of scope

Business-hours SLA clocks, ticket closure workflow, and reporting dashboards. The queue sheet can feed Looker Studio or Power BI.
