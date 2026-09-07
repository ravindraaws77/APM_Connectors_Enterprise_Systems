# Quickstart for consumers of this API

For anyone building against a running instance of this connector API —
another layer of APM, a script, or an agent hosted in Claude — without
needing to read this whole repo first. This doc points at the real
references rather than duplicating them; read those for anything not
answered here.

## The one thing every consumer needs: a base URL

Ask whoever deployed the instance you're targeting for its URL (e.g.
the `service_url` Terraform output from `infra/aws/ecs-fargate/`, or
`http://127.0.0.1:8000` for someone running it locally). Every example
below uses `$BASE_URL` for that.

**No authentication exists on this API today** (a known, documented
gap — see `docs/api-contract.md`'s "No auth today" note). Treat the URL
as sensitive: anyone who has it can call every route, including
proposing writes. Don't post it anywhere public.

## Option A: calling it directly from your own application

Read **`docs/api-contract.md`** — the full route list, request/response
shapes, and the propose → approve → execute flow. The two facts that
matter most:

- **Reads execute immediately.** `POST $BASE_URL/tools/gmail/search`,
  `.../calendar/search`, `.../excel/read`, etc. return real data with
  no approval step.
- **Writes never execute on the call that proposes them.**
  `.../gmail/send`, `.../calendar/create-event`, `.../excel/write`
  return a `pending_action` and `final_result: null`. Nothing happens
  in Gmail/Calendar/Excel until a human decision arrives at
  `POST $BASE_URL/tools/actions/{action_id}/decision` with
  `{"approved": true}` (or `false` to discard it). This is enforced
  server-side — there's no parameter that skips it, from any caller.

Any HTTP client in any language works — it's plain JSON over REST, no
SDK required.

## Option B: using it from Claude (Desktop or Claude Code)

This repo ships `apm_connectors_mcp` — an MCP server that exposes every
route above as an agent tool, so Claude can call `gmail_search`,
`gmail_send`, `calendar_create_event`, `decide_action`, etc. directly,
translating a free-text request into the right call itself. It's a
thin HTTP client over the same API — no separate deployment of the
connector logic needed.

1. Clone this repo and install the `mcp` extra:
   ```
   git clone https://github.com/ravindraaws77/apm_connectors_enterprise_systems.git
   cd apm_connectors_enterprise_systems
   pip install -e ".[mcp]"
   ```
2. Point it at the running API and register it with your Claude host.

   **Claude Desktop** — add to `claude_desktop_config.json`:
   ```json
   {
     "mcpServers": {
       "apm-connectors": {
         "command": "apm-connectors-mcp",
         "env": { "APM_CONNECTORS_BASE_URL": "https://your-base-url-here" }
       }
     }
   }
   ```

   **Claude Code** — either add the same shape to `.mcp.json`, or:
   ```
   claude mcp add apm-connectors --env APM_CONNECTORS_BASE_URL=https://your-base-url-here -- apm-connectors-mcp
   ```
3. Restart the Claude host. The tools listed in
   `src/apm_connectors_mcp/server.py` (their docstrings are the
   vocabulary Claude uses) should now be available — ask it something
   like "search my inbox for order 4521" and it calls `gmail_search`
   itself.

The approval gate applies exactly the same way here: Claude proposing
`gmail_send` doesn't send anything — it gets back a paused `action_id`
and has to call `decide_action` with `approved=true` to actually send
it, same as any other caller.

## Known limitations to plan around

- **No auth** (see above) — don't point this at anything but a trusted
  network/team for now.
- **HTTP, not HTTPS**, on the AWS deployment (`infra/aws/ecs-fargate/`)
  — see `docs/deployment.md`.
- **State is ephemeral** — a redeploy or task restart loses the audit
  log and any not-yet-decided pending actions (`src/apm_connectors/
  state/store.py`'s own docstring covers this).
- **Only whichever connectors are configured** are live — an
  unconfigured tool 503s cleanly rather than crashing (see
  `docs/capability-map.md` for what each one needs).
