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
  read the two secrets from SSM.
- Two SSM Parameter Store `SecureString` entries for the two OAuth
  client secrets (`GOOGLE_CLIENT_SECRET`, `MS_GRAPH_CLIENT_SECRET`) —
  never a plain environment variable.
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
ECS does **not** auto-detect a new image at the same tag on its own;
force a fresh deployment of the existing service after the push:

```
aws ecs update-service --cluster apm-connectors --service apm-connectors --force-new-deployment
```

## Changing connector configuration

Edit `terraform.tfvars` and re-run `terraform apply` — this changes the
task definition, which triggers ECS to roll a new deployment
automatically (no separate `force-new-deployment` needed in this case,
since the task definition itself changed). Secrets go into SSM as
`SecureString`s and are read by the container at startup; the
non-secret values (client IDs, tenant id, workbook path/Drive file id)
are set directly as plain environment variables in the task definition.

## Known limitations (MVP tradeoff, same as running locally)

- **State is ephemeral.** `src/apm_connectors/state/store.py` is a
  JSON file on the container's local disk (`APM_STATE_DIR`, default
  `/app/state` in the image). A Fargate task has no persistent
  storage — a redeploy or a task replacement loses the audit log and
  any paused (proposed-but-not-yet-decided) actions. Acceptable for
  this MVP; swapping the store for something durable (e.g. a small
  managed Postgres) is a later, non-MVP phase, same as noted in
  `src/apm_connectors/state/store.py`'s own module docstring.
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
