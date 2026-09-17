# Setting up a Salesforce + Jira test org for this project

For anyone provisioning a fresh Salesforce Developer Edition org and
Jira Cloud site to test these connectors, or to write/verify a new
business agent's `policy.yaml` in `apm_orchestrator` against them.
Complements `docs/capability-map.md` (which covers *credentials* —
Connected App, API token) with the UI navigation and verification steps
that trip people up the first time, live-verified during a real setup
session.

**The one rule underlying everything below:** a plausible-sounding
picklist value, issue type, or project key doesn't error when it's
wrong — it just silently returns nothing (a query) or 400s only once a
real write is finally approved (a create). Every gotcha here is a
version of "check the real system before writing it into a policy
file," not a one-off quirk. See `apm_orchestrator`'s
`FAILURES_AND_LESSONS_LEARNED.md` (its "live-test prep" section) for
the concrete bugs this caught.

## Salesforce

### Finding Setup and Object Manager

- Log in, then click the **gear icon (⚙️)** top-right → **Setup** (not
  "Service Setup" — some orgs default to a different app whose gear
  menu shows that instead).
- **Don't use the grid icon inside Setup itself** to look for
  Object Manager or standard objects — that's Setup's own app
  switcher (shows tiles like "Sales", "Service", "Developer Edition"),
  a different thing from the global App Launcher and from Object
  Manager.
- Fastest path: use the **Quick Find** search box inside the Setup
  page (not the global search bar) and type `Object Manager`, or skip
  it entirely and type the object's name directly (e.g. `Opportunity`)
  — it appears as a result under an "Object Manager" heading, and
  clicking it goes straight to that object's detail page.
- Direct URL, once you know your domain:
  `https://<your-domain>/lightning/setup/ObjectManager/<ObjectName>/FieldsAndRelationships/view`

### Creating actual records (Account/Contact/Opportunity)

Don't do this from Setup at all — Setup is for configuration
(objects, fields, users), not for using the CRM. From Setup's own app
switcher (the grid icon described above), click the **Sales** tile.
That opens the Sales app, which has **Accounts**/**Contacts**/
**Opportunities** as tabs in its top nav — create records there.

### Adding a custom field (e.g. for a new agent's `record_update`)

1. Object Manager → the object (e.g. Opportunity) → **Fields &
   Relationships** (left sidebar) → **New**.
2. Pick a data type (e.g. Text) → **Next**.
3. Enter a **Field Label** (e.g. `Onboarding Status`) — the **Field
   Name**/API name auto-fills, and Salesforce **always appends `__c`**
   to it (e.g. `Onboarding_Status__c`) — that's a platform rule, not a
   style choice, and it applies regardless of what the field is
   labeled in the UI.
4. **Field-Level Security step:** some orgs show this as step 3 of the
   wizard (check **Visible** for the profile your integration user
   has, leave **Read-Only** unchecked); others skip straight to "Add to
   page layouts" instead. If yours skips it, grant access afterward via
   **Setup → Profiles → \<your integration user's profile> → scroll to
   "Field-Level Security" → View next to the object → Edit → check
   Visible** (or, on a newer/"Enhanced" profile UI, **Object Settings →
   \<object> → Field Permissions**). **System Administrator** often
   already has full access to new fields by default even when the
   wizard skips this step — check before assuming you need to grant it.

### Finding your Connected App's "Run As" user

The Client Credentials Flow connector setup (`docs/capability-map.md`)
runs as a specific Salesforce user, not "whoever's logged in":
**Setup → App Manager → \<your Connected App> → dropdown ▼ → Manage
(or Edit Policies) → Client Credentials Flow → Run As**. Check that
user's **Profile** for the field-level-security step above, not just
whichever profile you happen to be logged in as.

### Never assume a picklist's values — check them

Standard Salesforce orgs do **not** ship with values like `"New
Business"`/`"Renewal"` on Opportunity's `Type` field — the real
default set is `New Customer` / `Existing Customer - Upgrade` /
`Existing Customer - Replacement` / `Existing Customer - Downgrade`.
Before writing `Type = '...'` (or any picklist filter) into a
`policy.yaml`, open the actual field's dropdown on a real record (or
Object Manager → the object → Fields & Relationships → the field →
scroll to its picklist values) and use exactly what's there — pick the
real value whose *meaning* matches what you need, not a value that
merely sounds right.

## Jira

### Newer UI naming: "Spaces" and "Work types"

Some Jira Cloud sites now use "Spaces" instead of "Projects" in the
sidebar, and "Work types" instead of "Issue types" in settings —
functionally the same concepts, just relabeled. Don't assume you're in
the wrong tool if the terminology doesn't match older Jira
documentation.

### Jumping straight to a project's settings

Menu-hunting in the newer UI can be slow. A direct URL usually works
regardless of the "Spaces" relabeling:

```
https://<your-site>.atlassian.net/jira/software/projects/<PROJECT_KEY>/settings/issuetypes
```

That lands on the project's configured work types directly (labeled
"Work types" in the sidebar even though the URL still says
`issuetypes`).

### Never assume an issue type exists — check it

A standard Kanban-template Jira project does **not** necessarily have
every issue type you might expect (`"Escalation"`, `"Onboarding"`, or
similar plausible-sounding names are common mistakes) — a real project
seen during this setup only had **Epic, Story, Task, Subtask**
configured. Before writing an issue type into a `policy.yaml`'s
`blocking_issue_types` (a matching list — a wrong value here just
silently never matches, no error) or an `issuetype` field for
`jira_create_issue` (a write — a wrong value here 400s only once a
human finally approves it, the most expensive point to find out),
check the real list at the URL above. `"Task"` is the one type close
to universal across Jira project templates — a safe default when in
doubt, not a guess.

### The project key itself

Every agent's `policy.yaml` ships with `REPLACE_WITH_YOUR_...`
placeholders for Jira project keys (see `apm_orchestrator`'s
`order_renewal/policy.yaml` and `customer_onboarding/policy.yaml`) —
these are deliberately never real values in the committed repo (see
`docs/security-guardrails.md`). Fill them in locally with your real
project key before testing; don't commit the real value.

## Reference

- `docs/capability-map.md` — credentials/auth setup for every
  connector, including Salesforce's Connected App and Jira's API token.
- `apm_orchestrator`'s `FAILURES_AND_LESSONS_LEARNED.md` — the concrete
  bugs this doc's warnings came from, with the full investigation for
  each.
- `apm_orchestrator`'s `CLAUDE.md` — the working convention this doc
  supports: never hardcode a plausible-sounding picklist value or issue
  type into a new agent's `policy.yaml` without checking it against the
  real org first.
