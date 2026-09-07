# Configuring which Google account the Gmail/Calendar connectors use

The Gmail and Calendar connectors act on whichever Google account
completes the OAuth consent flow — that's a separate thing from the
Google Cloud **OAuth client** (`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`
in `.env.example`), which one project owns and any number of Google
accounts can consent to. Pointing this at a different account (e.g. to
share a demo without using someone's personal/primary inbox) means
generating a new consented token for that account — it does **not**
require a new Google Cloud project or a new OAuth client.

## One-time: make sure the target account can consent at all

While this app is unverified (Google Cloud Console → **APIs & Services
→ OAuth consent screen** shows **Testing** as the publishing status),
only accounts explicitly listed as **test users** can complete consent
— anyone else sees a "this app hasn't been verified" hard block, not
just a warning.

1. Google Cloud Console → **APIs & Services → OAuth consent screen**
2. Scroll to **Test users** → **Add users**
3. Add the target Google account's email address → **Save**

(Up to 100 test users are allowed in Testing mode — no need to remove
the previous account first.)

## Generate a token for that account

The interactive consent flow (`src/apm_connectors/tools/google_auth.py`)
always uses whichever Google account you sign into in the browser it
opens — it doesn't ask which account in advance. If you're already
signed into a different Google account in that browser, the account
picker may auto-select it; explicitly choose "Use another account" (or
run this in a private/incognito window) to make sure the *target*
account signs the consent, not whichever one was already logged in.

1. Delete or rename any existing cached token so the flow can't reuse
   it instead of prompting fresh:
   ```
   del .google_token.json
   ```
2. With `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` already set in your
   local `.env` (same client as before — see `.env.example`), start the
   server locally:
   ```
   uvicorn apm_connectors.api.app:app --reload --port 8000
   ```
3. In a new terminal, trigger consent with any Gmail/Calendar call:
   ```
   curl -X POST http://127.0.0.1:8000/tools/gmail/search -H "Content-Type: application/json" -d "{\"query\": \"in:inbox\"}"
   ```
4. A browser opens. Sign in as the **target** account (see the note
   above about account switching), review the consent screen (it'll
   list Gmail read+send and Calendar read+events scopes — both, even if
   you only care about one, since `get_tools()` requests them together
   — see `google_auth.build_gmail_and_calendar_tools`'s docstring), and
   approve.
5. `.google_token.json` now holds a token for the target account. The
   `curl` call above should return that account's real inbox contents,
   confirming which account is actually wired up.

## Using it

- **Locally**: nothing further needed — `.google_token.json` is picked
  up automatically by the interactive-flow code path on every
  subsequent run, for as long as its `refresh_token` stays valid.
- **On the AWS deployment** (`infra/aws/ecs-fargate/`): this headless
  environment can't run the interactive flow itself (see
  `docs/deployment.md`'s "Enabling real Gmail/Calendar on this
  deployment" section) — copy `.google_token.json`'s contents into
  `terraform.tfvars`'s `google_token_json`, or set
  `TF_VAR_google_token_json` from the file directly (avoids
  hand-escaping the JSON — see that same doc section), then
  `terraform apply`. This replaces whichever account's token was
  wired in before.

## Switching accounts again later

Repeat "Generate a token for that account" above with the new target
account — no code or Terraform changes needed beyond re-running
`apply` with the new token content, since the app itself has no
concept of "whose account this is" beyond whatever token it's handed.
