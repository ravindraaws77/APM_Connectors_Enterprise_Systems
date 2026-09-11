# Deploying to AWS (ECS on Fargate)

This deploys the connector API only (`src/apm_connectors/api`) as a
standalone HTTP service — no reasoning/orchestration layer, no
dashboard. It's the same contract `docs/api-contract.md` describes,
just reachable at a public URL instead of `127.0.0.1:8000`.

> Originally built on AWS App Runner. App Runner stopped accepting new
> customers as of 2026-04-30 (AWS notice) and is no longer taking new
> features, so this was rebuilt on ECS Fargate — mature, fully
> supported, and the direct replacement AWS itself points to.

Infra lives in `infra/aws/ecs-fargate/` as Terraform, so the actual AWS
resources are created by you running `terraform apply` from a shell
where your own AWS credentials live — nothing here holds or needs
your AWS credentials itself.

## What gets created

- An ECR repository, and the Docker image (repo-root `Dockerfile`)
  built and pushed into it as part of `terraform apply`.
- A public Application Load Balancer, health-checking `/health`, in
  the account's **default VPC** (no new network to stand up for an
  MVP deploy — its subnets are public by default).
- An ECS cluster running the image as a Fargate task, reachable only
  from the ALB (a dedicated security group blocks any other inbound
  traffic to the task).
- An execution role the task uses to pull the image, write logs, and
  read the secrets from SSM.
- Three SSM Parameter Store `SecureString` entries for the connectors'
  secrets (`GOOGLE_CLIENT_SECRET`, `SALESFORCE_CLIENT_SECRET`,
  `JIRA_API_TOKEN`) — never a plain environment variable.
- A CloudWatch log group for the container's stdout/stderr.

Every connector env var is optional and empty by default, exactly like
an unfilled-in local `.env` (see `.env.example`): leave one unset and
its `/tools/*` routes just 503 until you configure it — the service
still deploys and passes its health check with zero connectors wired up.

## Prerequisites

- An AWS account with permissions to create ECR repos, IAM roles, SSM
  parameters, VPC security groups, an ALB, and ECS resources.
- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.5
- Docker Desktop (or another `buildx`-capable Docker), running locally
  — the build/push step shells out to `docker buildx build --platform
  linux/amd64`, which cross-compiles for Fargate's required x86_64
  even if `terraform apply` itself runs on an ARM machine (Apple
  Silicon, Windows-on-ARM). Docker Desktop supports this out of the
  box, no extra setup.
- AWS CLI v2, configured with credentials for that account
  (`aws configure`, or an SSO/profile setup — `terraform apply` and the
  `aws ecr` login it runs both use your default credential chain)
- **On Windows**: run `terraform apply` from a bash-capable shell (Git
  Bash or WSL), not plain Command Prompt/PowerShell — the build/push
  step's script uses bash syntax that `cmd.exe` can't run. If `where
  bash` lists more than one match (e.g. the legacy WSL launcher in
  `System32`), make sure Git's `bin` directory (with the real Git Bash)
  comes first on PATH.
- A brand-new AWS account may need a day to fully activate before some
  services work — if you see `SubscriptionRequiredException` or a
  "complete your account setup" banner in the console, that's an
  AWS-side account activation gate, not a problem with this Terraform.

## Deploy

```
cd infra/aws/ecs-fargate
cp terraform.tfvars.example terraform.tfvars   # fill in whichever connectors you want live
terraform init
terraform apply
```

`terraform apply` builds the Docker image, pushes it to the ECR repo it
just created, and stands up the ECS service + ALB in front of it. On
success it prints `service_url` — the public HTTP URL of the API.

Verify it's up (allow a minute or two after `apply` finishes for the
task to pass its first health check and register with the ALB):

```
curl http://<service_url>/health
python scripts/api_smoke_test.py --base-url http://<service_url>
```

## Updating a running deployment

After a source change:

```
terraform apply
```

The build/push step re-runs automatically — its trigger is a content
hash of `src/` and the `Dockerfile`, so it only rebuilds when something
that would actually change the image has changed. Unlike App Runner,
ECS does **not** auto-detect a new image at the same tag on its own —
but `terraform apply` handles this itself
(`null_resource.force_new_deployment` forces a fresh deployment
whenever the build/push step re-runs), so no separate manual
`aws ecs update-service --force-new-deployment` step is needed.

## Changing connector configuration

Edit `terraform.tfvars` (client IDs, tenant id, workbook path/Drive
file id, or any of the secret values) and re-run `terraform apply`.
Secrets go into SSM as `SecureString`s and are read by the container at
startup; non-secret values are set directly as plain environment
variables in the task definition.

Changing a *secret's value* (e.g. rotating `GOOGLE_TOKEN_JSON` — see
"Enabling real Gmail/Calendar" below) only updates the SSM parameter's
value, not its ARN, which the task definition doesn't see as a change
on its own. `terraform apply` handles this the same way as an image
update — `null_resource.force_new_deployment` forces the redeploy the
task definition's own diff wouldn't have triggered.

## Enabling real Gmail/Calendar on this deployment

The Gmail/Calendar connectors' default OAuth flow
(`src/apm_connectors/tools/google_auth.py`) opens a browser and catches
the redirect on `localhost` — that can't run inside this headless
container. Instead:

1. Run the local interactive consent flow once, following
   `docs/running-locally.md` (set `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`
   in a local `.env`, start the server locally, and make one `/tools/gmail/*`
   or `/tools/calendar/*` call — a browser opens for you to sign in).
   This produces a `.google_token.json` file in your working directory.
2. Copy that file's full contents into `terraform.tfvars`:
   ```
   google_token_json = "{\"token\": \"...\", \"refresh_token\": \"...\", ...}"
   ```
   (a single-line JSON string, escaped as a Terraform string literal)
3. `terraform apply` — this creates a `GOOGLE_TOKEN_JSON` SSM
   `SecureString` and wires it into the task definition, taking
   precedence over `google_client_id`/`google_client_secret` in the
   deployed app.

The token's `refresh_token` keeps working indefinitely (Google doesn't
rotate it on use), so this is a one-time setup, not something to repeat
per deploy — unless the consent is revoked from the Google account side.

## Enabling real Salesforce on this deployment

Unlike Gmail/Calendar, Salesforce uses the OAuth 2.0 Client Credentials
Flow (`src/apm_connectors/tools/salesforce_auth.py`) — a server-to-server
exchange with no browser/redirect step, so it needs no local
pre-flight like `google_token_json` does. Just set, in
`terraform.tfvars`:

```
salesforce_client_id     = "..."
salesforce_client_secret = "..."
salesforce_domain        = "my-org-dev-ed.develop.my.salesforce.com"
# salesforce_api_version = "v60.0"  # optional, defaults to salesforce_tool.DEFAULT_API_VERSION
```

then `terraform apply`. `salesforce_client_secret` is stored as an SSM
`SecureString`, the same as the Google client secret; the other three
are plain environment variables on the task, since they're not
sensitive on their own.

## Enabling real Jira on this deployment

Like Salesforce, Jira needs no interactive/browser flow — it
authenticates with a plain Atlassian API token (Basic auth: account
email + token), so there's no local pre-flight step either. Just set,
in `terraform.tfvars`:

```
jira_base_url = "https://yourcompany.atlassian.net"
jira_email    = "you@yourcompany.com"
jira_api_token = "..."
```

then `terraform apply`. `jira_api_token` is stored as an SSM
`SecureString`, the same as the Google/Salesforce secrets;
`jira_base_url`/`jira_email` are plain environment variables on the
task, since they're not sensitive on their own.

## Enabling durable state (Postgres) on this deployment

By default the connector API's status/audit store is a JSON file on
the container's local disk, and paused (proposed-but-not-yet-decided)
actions live in the LangGraph checkpointer's memory — both lost on a
redeploy or task replacement, since a Fargate task has no persistent
local storage (see "Known limitations" below). Point the deployment at
a real Postgres instance (RDS, or any reachable Postgres) to fix that:

```
database_url = "postgresql://user:password@host:5432/apm"
```

then `terraform apply`. `database_url` is stored as an SSM
`SecureString`, the same as the other secrets, and — unlike them —
only created and attached to the task at all when set: leaving it
unset keeps today's default file-backed/in-memory behavior exactly as
before, no empty/placeholder connection string involved. The app
creates its tables on first use (`src/apm_connectors/state/postgres_store.py`,
plus the LangGraph checkpointer's own `checkpoint*` tables) — no
separate migration step or `terraform apply` needed to set up schema
once the database itself exists and is reachable from the task's
security group (`aws_security_group.service` — an RDS instance in the
same VPC needs to allow inbound from it).

This Terraform module doesn't provision the Postgres instance itself
(RDS, Aurora Serverless, or otherwise) — only wires up `database_url`
once you have one. Standing up RDS in the default VPC this module
uses is straightforward but out of scope here to keep the module's own
blast radius small; a security group allowing inbound Postgres
(5432/tcp) from `aws_security_group.service` is the only piece that
needs to reference this module's resources.

For quick testing with no AWS resource to stand up at all, a free
managed Postgres (e.g. [Neon](https://neon.tech)) works too — its
connection string already includes `sslmode=require`, and the task's
security group needs no changes since it's reached over the public
internet, not the VPC (`assign_public_ip = true` already gives the
task outbound internet access). This is live-verified: propose a
write → `aws ecs update-service --force-new-deployment` → the pending
action and audit trail are still there on the brand-new task → approve
it → it executes for real. One thing to know with a serverless
provider like Neon: it auto-suspends its compute after a few idle
minutes, which surfaces as `SSL connection has been closed
unexpectedly` on the first call after a while unless the pool detects
and replaces the dead connection — both pools here do
(`check=ConnectionPool.check_connection` in `state/postgres_store.py`
and `api/dependencies.py`), so this recovers on its own.

## Known limitations (MVP tradeoff, same as running locally)

- **State is ephemeral unless `database_url` is set.** See "Enabling
  durable state (Postgres) on this deployment" above — with no
  `database_url`, a redeploy or task replacement loses the audit log
  and any paused (proposed-but-not-yet-decided) actions.
- **HTTP, not HTTPS.** The ALB listens on plain HTTP:80 for
  simplicity — there's no domain name or ACM certificate wired up here.
  Add an HTTPS listener (ACM cert + a domain in Route 53 or elsewhere)
  before putting anything sensitive through this beyond local testing.
- **Cost.** Unlike App Runner's pay-per-use pricing, an Application
  Load Balancer bills an hourly rate regardless of traffic (roughly
  $16-20/month left running continuously), on top of the Fargate task's
  compute time, ECR storage, and CloudWatch Logs. Run
  `terraform destroy` from `infra/aws/ecs-fargate/` to tear everything
  down when you're done with it.

## Local Docker (no AWS)

To sanity-check the same image locally, without deploying anything:

```
docker build -t apm-connectors .
docker run -p 8000:8000 --env-file .env apm-connectors
curl http://127.0.0.1:8000/health
```

## Integration tests

`tests/integration/` exercises the full API — the propose → approve →
execute contract this deployment serves — against a real running
server process over real HTTP, the same way an external
reasoning/orchestration layer or `scripts/api_smoke_test.py` would.
Like the rest of the test suite, it uses fake connector clients and
needs no live credentials or AWS deployment to run:

```
pytest tests/integration -q
```
