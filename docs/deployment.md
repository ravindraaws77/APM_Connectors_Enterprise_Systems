# Deploying to AWS (App Runner)

This deploys the connector API only (`src/apm_connectors/api`) as a
standalone HTTPS service — no reasoning/orchestration layer, no
dashboard. It's the same contract `docs/api-contract.md` describes,
just reachable at a public URL instead of `127.0.0.1:8000`.

Infra lives in `infra/aws/apprunner/` as Terraform, so the actual AWS
resources are created by you running `terraform apply` from a shell
where your own AWS credentials live — nothing here holds or needs
your AWS credentials itself.

## What gets created

- An ECR repository, and the Docker image (repo-root `Dockerfile`)
  built and pushed into it as part of `terraform apply`.
- An IAM role App Runner uses to pull that image, and a separate
  instance role the running container uses to read secrets.
- Two SSM Parameter Store `SecureString` entries for the two OAuth
  client secrets (`GOOGLE_CLIENT_SECRET`, `MS_GRAPH_CLIENT_SECRET`) —
  never a plain environment variable.
- The App Runner service itself, with a health check against `/health`.

Every connector env var is optional and empty by default, exactly like
an unfilled-in local `.env` (see `.env.example`): leave one unset and
its `/tools/*` routes just 503 until you configure it — the service
still deploys and passes its health check with zero connectors wired up.

## Prerequisites

- An AWS account with permissions to create ECR repos, IAM roles, SSM
  parameters, and App Runner services.
- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.5
- Docker Desktop (or another `buildx`-capable Docker), running locally
  — the build/push step shells out to `docker buildx build --platform
  linux/amd64`, which cross-compiles for App Runner's required x86_64
  even if `terraform apply` itself runs on an ARM machine (Apple
  Silicon, Windows-on-ARM). Docker Desktop supports this out of the
  box, no extra setup.
- AWS CLI v2, configured with credentials for that account
  (`aws configure`, or an SSO/profile setup — `terraform apply` and the
  `aws ecr` login it runs both use your default credential chain)
- **On Windows**: run `terraform apply` from a bash-capable shell (Git
  Bash or WSL), not plain Command Prompt/PowerShell — the build/push
  step's script uses bash syntax that `cmd.exe` can't run.

## Deploy

```
cd infra/aws/apprunner
cp terraform.tfvars.example terraform.tfvars   # fill in whichever connectors you want live
terraform init
terraform apply
```

`terraform apply` builds the Docker image, pushes it to the ECR repo it
just created, and stands up the App Runner service against that image.
On success it prints `service_url` — the public HTTPS URL of the API.

Verify it's up:

```
curl https://<service_url>/health
python scripts/api_smoke_test.py --base-url https://<service_url>
```

## Updating a running deployment

After a source change:

```
terraform apply
```

The build/push step re-runs automatically — its trigger is a content
hash of `src/` and the `Dockerfile`, so it only rebuilds when something
that would actually change the image has changed. `auto_deployments_enabled`
is on, so once the new image lands in ECR at the same `:latest` tag, App
Runner detects the digest change and redeploys on its own — typically
within a few minutes, no extra command needed.

## Changing connector configuration

Edit `terraform.tfvars` and re-run `terraform apply`. Secrets go into
SSM as `SecureString`s and are read by the container at startup; the
non-secret values (client IDs, tenant id, workbook path/Drive file id)
are set directly as the App Runner service's environment variables.

## Known limitations (MVP tradeoff, same as running locally)

- **State is ephemeral.** `src/apm_connectors/state/store.py` is a
  JSON file on the container's local disk (`APM_STATE_DIR`, default
  `/app/state` in the image). App Runner containers are not
  persistent storage — a redeploy or an instance replacement loses the
  audit log and any paused (proposed-but-not-yet-decided) actions.
  Acceptable for this MVP; swapping the store for something durable
  (e.g. a small managed Postgres) is a later, non-MVP phase, same as
  noted in `src/apm_connectors/state/store.py`'s own module docstring.
- **Cost.** ECR storage, App Runner compute (even at the smallest
  `0.25 vCPU` / `0.5 GB` instance size, the default here), and Elastic
  Network Interface time while the service is running with the default
  private-VPC-egress-less configuration all incur AWS charges. Run
  `terraform destroy` from `infra/aws/apprunner/` to tear everything
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
