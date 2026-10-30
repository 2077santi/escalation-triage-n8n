# Runbook - Escalation Triage Automation

**Owner:** Ops manager · **Reviewed:** with every policy change

## 1. Setup (one time, ~30 minutes)

1. **Queue sheet.** Create a Google Sheet with a tab named `Queue` and this header row:
   `ticket_id, created_at, reporter, text, category, impact, urgency, summary, confidence, reasoning, priority, team, channel, sla_minutes, response_due_at, page_on_call, needs_human_review, status, first_response_at, last_alert`
2. **Credentials in n8n.**
   - *HTTP Header Auth*, name `Anthropic`: header `x-api-key`, value = your Anthropic API key.
   - *Google Sheets OAuth2* and *Slack OAuth2* (bot needs `chat:write` in every routing channel).
3. **Import** `n8n/escalation-triage.json` and `n8n/sla-watchdog.json`. In each Google Sheets node, set the document ID. In *Classify with Claude*, select the `Anthropic` credential.
4. **Channels.** Create the channels in `policy.js` → `ROUTING`, plus `#ops-oncall`, and invite the bot.
5. **Smoke test.** With the workflow in test mode:
   ```bash
   curl -X POST https://<your-n8n>/webhook-test/escalation \
     -H 'Content-Type: application/json' \
     -d '{"reporter":"Team lead","text":"Labeling tool returns 502 for the whole team, batch due today"}'
   ```
   Expect: P1, Tooling & IT, a row in the sheet, a message in `#ops-tooling` and a page in `#ops-oncall`.
6. **Activate** both workflows.

## 2. Daily operation

| Who | What |
|---|---|
| Owning team | Reply in the ticket thread, then fill `first_response_at` in the sheet (ISO time). That stops the SLA clock. |
| Owning team | Set `status` to `closed` when resolved. |
| Ops triage | Every ticket with `needs_human_review = TRUE`: correct category/priority in the sheet and forward it. |
| Ops manager | Weekly: SLA met %, tickets by category, low-confidence share. If the low-confidence share is above 10%, review the prompt. |

## 3. Changing the policy

1. Edit `workflow/policy.js` (matrix, SLA minutes, routing) or `workflow/classifier.json` (prompt).
2. `make test`: all tests must pass.
3. For prompt changes, run `make eval`: **no missed P1s**, and accuracy no worse than the last run.
4. `make build`, then re-import the workflows in n8n (or paste the updated Code node).
5. Note the change and the eval result in the PR description.

## 4. Incidents

| Symptom | Likely cause | Action |
|---|---|---|
| All tickets arrive as `needs_human_review`, reasoning "Classifier unavailable" | Anthropic API key invalid/expired, or API outage | Check the *Classify with Claude* execution log; rotate the key in the credential. Triage manually meanwhile. Nothing is lost. |
| No Slack messages | Slack token revoked or bot removed from channel | Re-authorize the credential; `/invite` the bot. Tickets are still in the sheet. |
| Watchdog silent | Workflow deactivated or sheet renamed | Check executions every 15 min; the tab must be named `Queue`. |
| Duplicate alerts | `last_alert` column missing or renamed | Restore the column. |
| A ticket got the wrong priority | Classification error | Fix it in the sheet. Add the ticket (anonymized) to `samples/tickets.jsonl` with the correct labels so the next eval catches it. |

## 5. Data handling

- Ticket text is sent to the Anthropic API for classification. Tell reporters **not to paste personal data or client content** into the form, only describe the issue.
- The sheet is the system of record. Restrict edit access to ops leads and owning teams.
