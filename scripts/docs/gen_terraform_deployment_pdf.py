# -*- coding: utf-8 -*-
"""Generate 'Deployment -- infra/aws/ecs-fargate/ (Terraform)' reference PDF:
a from-zero tutorial on Terraform/HCL and the AWS primitives this module
uses (for a reader new to both, same spirit as the Python-layer docs'
Part 0s but for a different language/domain), why this deployment is
shaped the way it is, a complete file-by-file deep dive into the actual
module, the infrastructure-as-code patterns it uses, and interview-prep
Q&A. See scripts/docs/README.md for the overall doc-generation convention.

Run standalone with `python scripts/docs/gen_terraform_deployment_pdf.py`;
writes docs/terraform-deployment-reference.pdf by default (override with
the OUT_OVERRIDE env var). Re-run after any change to
infra/aws/ecs-fargate/{main,variables,outputs}.tf or docs/deployment.md.
"""

import os
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from _pdf_template import (
    CODE_BORDER, GRAY_FILL, MARGIN, USABLE_W,
    bl, caption, code_block, esc, footer, h1, h2, quote_block, rule, simple_table, styles,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get("OUT_OVERRIDE", REPO_ROOT / "docs" / "terraform-deployment-reference.pdf"))

story = []

# ===========================================================================
story.append(Paragraph("Deployment — infra/aws/ecs-fargate/ (Terraform)", styles["title"]))
story.append(Paragraph(
    "A from-zero tutorial on Terraform/HCL and the AWS building blocks this module uses, why this "
    "deployment is shaped the way it is, a complete file-by-file deep dive into the actual module, the "
    "infrastructure-as-code patterns it applies, and interview-prep Q&amp;A — written as a standalone "
    "reference for a reader new to both Terraform and AWS.",
    styles["subtitle"],
))
story.append(rule())

# ---------------------------------------------------------------------------
# PART 0 — TERRAFORM / HCL, FROM ZERO
# ---------------------------------------------------------------------------
story.append(h1("Part 0 — Terraform / HCL, from zero"))
story.append(bl(
    "This is a different domain from the connector-layer docs' Python primers — Terraform's config "
    "language, HCL (HashiCorp Configuration Language), is declarative, not imperative: you describe "
    "the infrastructure you want to <i>exist</i>, not the steps to create it. No prior Terraform or AWS "
    "knowledge assumed."
))

story.append(h2("0.1 The core idea: desired state, not a script"))
story.append(bl(
    "A Terraform <b>.tf</b> file is a description of what should exist — \"there should be an ECR "
    "repository named apm-connectors,\" not \"run this command to create one.\" Terraform's job is to "
    "compare that description against what actually exists in AWS right now (tracked in a "
    "<b>state file</b>, <font name='Courier'>terraform.tfstate</font>) and figure out, itself, what to "
    "create/change/destroy to close the gap. Run the same config twice with nothing changed, and the "
    "second run does nothing — this property is called <b>idempotence</b> (the connector-layer doc's "
    "§1.4 used the same word for a different context: same idea, \"doing it again changes nothing\")."
))

story.append(h2("0.2 The four commands you actually run"))
story.append(simple_table(
    [
        ["<b>Command</b>", "<b>What it does</b>"],
        ["terraform init", "Downloads the providers a config needs (here: hashicorp/aws, hashicorp/null) -- run once per checkout, or after adding a provider."],
        ["terraform plan", "Shows what apply would change, without changing anything -- a dry run in the same spirit as the connector layer's dry_run (that doc, §1.3)."],
        ["terraform apply", "Reconciles real AWS resources to match the config -- creates/updates/destroys whatever plan identified, after you confirm."],
        ["terraform destroy", "Tears down every resource this config created. Used here to stop paying for the ALB/Fargate task when done (docs/deployment.md's 'Known limitations')."],
    ],
    [1.7 * inch, USABLE_W - 1.7 * inch],
))

story.append(h2("0.3 Blocks: the five shapes you'll see in this module"))
story.append(code_block(
    "provider \"aws\" { region = var.aws_region }         # configures a plugin\n\n"
    "resource \"aws_ecr_repository\" \"this\" {             # a thing Terraform creates/owns\n"
    "  name = var.app_name\n"
    "}\n\n"
    "data \"aws_vpc\" \"default\" { default = true }         # reads something that already exists\n\n"
    "variable \"app_name\" {                                # an input, filled in by terraform.tfvars\n"
    "  type    = string\n"
    "  default = \"apm-connectors\"\n"
    "}\n\n"
    "output \"service_url\" {                                # a value printed after apply\n"
    "  value = \"http://${aws_lb.this.dns_name}\"\n"
    "}\n"
))
story.append(bl(
    "<font name='Courier'>resource</font> is the one you'll see most — each one is a real AWS object "
    "Terraform will create, and will destroy if removed from the config or on "
    "<font name='Courier'>terraform destroy</font>. Its two quoted labels are the resource "
    "<i>type</i> (<font name='Courier'>aws_ecr_repository</font> — which AWS thing) and a local "
    "<i>name</i> (<font name='Courier'>this</font> — how <i>this config</i> refers to it; not an AWS "
    "name). <font name='Courier'>data</font> looks almost identical but never creates or destroys "
    "anything — it just reads something that already exists (here, the account's default VPC) so other "
    "resources can reference it. <font name='Courier'>variable</font> and "
    "<font name='Courier'>output</font> are the module's inputs and outputs — the FastAPI doc's "
    "request/response shapes, for infrastructure."
))

story.append(h2("0.4 References build an implicit dependency graph"))
story.append(code_block(
    "resource \"aws_ecr_repository\" \"this\" {\n"
    "  name = var.app_name\n"
    "}\n\n"
    "resource \"aws_ecs_task_definition\" \"this\" {\n"
    "  # references the ECR repo's computed URL -- a value AWS assigns,\n"
    "  # not something the config writer picks\n"
    "  container_definitions = jsonencode([{ image = \"${aws_ecr_repository.this.repository_url}:latest\" }])\n"
    "}\n"
))
story.append(bl(
    "<font name='Courier'>aws_ecr_repository.this.repository_url</font> — "
    "<font name='Courier'>&lt;type&gt;.&lt;name&gt;.&lt;attribute&gt;</font> — reads an attribute off "
    "another resource, including ones AWS itself computes (a repository's URL isn't known until AWS "
    "creates it). Writing this reference is also how you tell Terraform <i>the task definition depends "
    "on the ECR repo existing first</i> — you never write \"create A before B\" explicitly; Terraform "
    "derives the entire creation order from which resources reference which. This is the same "
    "declarative-over-imperative idea as §0.1, one level more concrete."
))

story.append(h2("0.5 String interpolation and heredocs"))
story.append(code_block(
    "name = \"${var.app_name}-alb\"        # interpolation: embed an expression in a string\n\n"
    "command = <<-EOT                     # heredoc: a multi-line string, indentation-stripped\n"
    "  set -euo pipefail\n"
    "  docker buildx build --platform linux/amd64 \\\n"
    "    -t ${aws_ecr_repository.this.repository_url}:${var.image_tag} --push .\n"
    "EOT\n"
))
story.append(bl(
    "<font name='Courier'>${...}</font> inside a string embeds any expression's value — variables, "
    "resource attributes, function calls. A <font name='Courier'>&lt;&lt;-EOT ... EOT</font> heredoc is "
    "how a multi-line value (here, an entire bash script) gets written without escaping every newline — "
    "the module uses this for the Docker build/push script (§2.2) and the force-redeploy script (§2.8), "
    "both handed to <font name='Courier'>local-exec</font> (§0.7)."
))

story.append(h2("0.6 count — conditional and repeated resources"))
story.append(code_block(
    "resource \"aws_ssm_parameter\" \"database_url\" {\n"
    "  count = var.database_url != \"\" ? 1 : 0    # 1 if set, 0 (i.e. don't create it) if not\n"
    "  name  = \"/${var.app_name}/DATABASE_URL\"\n"
    "  value = var.database_url\n"
    "}\n\n"
    "# elsewhere, referencing a count-based resource needs an index:\n"
    "aws_ssm_parameter.database_url[0].arn\n"
))
story.append(bl(
    "<font name='Courier'>count</font> on a resource block turns it into a list of 0 or more instances "
    "— set to a ternary like <font name='Courier'>condition ? 1 : 0</font>, this is Terraform's way of "
    "saying \"only create this resource if...\", since HCL has no plain "
    "<font name='Courier'>if</font> statement. This module uses exactly this for "
    "<font name='Courier'>google_token_json</font> and <font name='Courier'>database_url</font> (§2.6) "
    "— both optional secrets that, unlike the three always-created ones, shouldn't exist as an SSM "
    "parameter at all when unset. Referencing a <font name='Courier'>count</font>-based resource "
    "elsewhere always needs an index, even when there's at most one — "
    "<font name='Courier'>[0]</font>, guarded by the same condition."
))

story.append(h2("0.7 for expressions, jsonencode, and functions"))
story.append(code_block(
    "locals {\n"
    "  source_hash = sha1(join(\"\", [\n"
    "    for f in fileset(local.repo_root, \"src/**/*\") : filesha1(\"${local.repo_root}/${f}\")\n"
    "  ]))\n"
    "}\n\n"
    "container_definitions = jsonencode([{ name = var.app_name, image = \"...\" }])\n"
))
story.append(bl(
    "<font name='Courier'>[for f in ... : ...]</font> is a <b>for expression</b> — the same "
    "list-comprehension shape the connector-layer doc's §0.6 covered in Python "
    "(<font name='Courier'>[expr for item in iterable]</font>), here building a list of file hashes "
    "instead of a list of dict values. <font name='Courier'>fileset</font>/<font name='Courier'>filesha1</font>/"
    "<font name='Courier'>sha1</font>/<font name='Courier'>join</font> are Terraform's built-in "
    "functions (there's no way to define your own) — this specific chain is how "
    "<font name='Courier'>local.source_hash</font> (§2.1, §2.8) is computed: hash every tracked source "
    "file, then hash the list of hashes into one value. "
    "<font name='Courier'>jsonencode(...)</font> turns an HCL value (a list of objects here) into a "
    "JSON string at plan time — ECS's <font name='Courier'>container_definitions</font> argument is "
    "literally a JSON string, not a native Terraform type, so this is how HCL data becomes it."
))

story.append(h2("0.8 The escape hatch: provisioners, null_resource, and triggers"))
story.append(bl(
    "Terraform models AWS resources declaratively — but building a Docker image and pushing it isn't "
    "an AWS resource at all; it's an imperative action with side effects Terraform has no built-in "
    "concept of. <font name='Courier'>null_resource</font> plus a "
    "<font name='Courier'>local-exec</font> provisioner is the escape hatch for exactly this:"
))
story.append(code_block(
    "resource \"null_resource\" \"docker_build_push\" {\n"
    "  triggers = {\n"
    "    source_hash = local.source_hash   # re-run ONLY when this value changes between applies\n"
    "  }\n"
    "  provisioner \"local-exec\" {\n"
    "    interpreter = [\"bash\", \"-c\"]\n"
    "    command     = \"docker buildx build ... --push .\"\n"
    "  }\n"
    "}\n"
))
story.append(bl(
    "A <font name='Courier'>null_resource</font> manages nothing in AWS by itself — it exists purely "
    "to attach a <font name='Courier'>provisioner</font> (an arbitrary local command) to Terraform's "
    "apply lifecycle. Its <font name='Courier'>triggers</font> map is the only thing that decides "
    "whether it re-runs: Terraform compares each trigger value to what it was on the last apply, and "
    "re-runs the provisioner only if something in that map actually changed. Without a trigger, "
    "<font name='Courier'>local-exec</font> would only run once, ever, on first creation — this module "
    "uses <font name='Courier'>triggers</font> deliberately, twice (§2.2, §2.8), to make an otherwise "
    "invisible-to-Terraform change (new source code; a changed secret value) actually cause something "
    "to happen on the next <font name='Courier'>apply</font>."
))

story.append(rule())

# ---------------------------------------------------------------------------
# PART 1 — WHY THIS DEPLOYMENT IS SHAPED THIS WAY, FROM ZERO
# ---------------------------------------------------------------------------
story.append(h1("Part 1 — Why this deployment is shaped this way, from zero"))

story.append(h2("1.1 The problem: run a FastAPI container somewhere public"))
story.append(bl(
    "The FastAPI doc covered <font name='Courier'>uvicorn</font> serving the app on "
    "<font name='Courier'>127.0.0.1:8000</font> — fine on a laptop, useless to anyone else. Deploying "
    "means: package the app so it runs the same way anywhere (a <b>container</b> — the repo-root "
    "Dockerfile builds one, installing this package and running the exact same "
    "<font name='Courier'>uvicorn</font> command inside it), run that container on a machine reachable "
    "from the public internet, and keep it running (restart it if it crashes, replace it on a new "
    "deploy) without babysitting it by hand."
))

story.append(h2("1.2 ECS Fargate: containers without managing servers"))
story.append(bl(
    "<b>ECS</b> (Elastic Container Service) is AWS's service for running containers; "
    "<b>Fargate</b> is one way to run them — \"serverless\" in the sense that you never provision or "
    "patch an EC2 virtual machine yourself. You describe a <b>task definition</b> (what image, how much "
    "CPU/memory, what ports) and AWS finds the underlying capacity to run it. The module's comment "
    "notes this replaced an earlier design on <b>App Runner</b> (an even higher-level \"just run this "
    "container\" service) after AWS stopped accepting new App Runner customers — Fargate is one layer "
    "more manual (you define the load balancer and networking yourself, §1.3) but has no such "
    "sunset risk, being a mature, widely-used AWS service."
))

story.append(h2("1.3 The network model: default VPC, a public ALB, and a private task"))
story.append(bl(
    "A few AWS networking primitives, each doing one job here:"
))
story.append(simple_table(
    [
        ["<b>Primitive</b>", "<b>What it is</b>", "<b>Its job in this module</b>"],
        ["VPC", "An isolated virtual network in your AWS account", "Every account gets a default one for free -- this module reuses it (§1.3 below) instead of building a new one."],
        ["Subnet", "A slice of a VPC's IP range, in one availability zone", "The default VPC's subnets are public (route to an Internet Gateway) -- used as-is for both the ALB and the task."],
        ["Security group", "A stateful firewall attached to a resource", "Two are defined (§2.3): one lets the public reach the ALB; the other lets only the ALB reach the task."],
        ["ALB", "Application Load Balancer -- an HTTP(S) reverse proxy AWS runs for you", "The one fixed public entry point; health-checks /health and forwards to the running task."],
    ],
    [1.0 * inch, 2.0 * inch, USABLE_W - 3.0 * inch],
))
story.append(bl(
    "The deliberate choice worth understanding is <b>reusing the account's default VPC</b> rather than "
    "building a dedicated one. A from-scratch VPC for production usually adds private subnets plus a "
    "<b>NAT Gateway</b> so a task can reach the internet (to pull its image, call Gmail/Salesforce/Jira) "
    "without a public IP of its own — safer, but a NAT Gateway alone costs roughly as much per month as "
    "the ALB. This module instead gives the task a public IP directly "
    "(<font name='Courier'>assign_public_ip = true</font>, §2.7) in the default VPC's already-public "
    "subnets, and relies entirely on the <b>security group</b> — not network topology — to stop the "
    "public from reaching it: only the ALB's security group may reach port 8000 (§2.3). A public IP "
    "existing is not the same as being reachable; the security group is the actual gate."
))

story.append(h2("1.4 Secrets: SSM Parameter Store instead of plain environment variables"))
story.append(bl(
    "A plain environment variable on a task definition is visible to anyone who can read that task "
    "definition via the AWS console or CLI — fine for a non-secret value like "
    "<font name='Courier'>JIRA_BASE_URL</font>, wrong for a client secret or API token. "
    "<b>SSM Parameter Store</b>'s <font name='Courier'>SecureString</font> type encrypts the value at "
    "rest (via AWS KMS) and requires an explicit IAM permission "
    "(<font name='Courier'>ssm:GetParameters</font>, §2.5) to read it back — a real access-control "
    "boundary, not just a naming convention. ECS's task definition <font name='Courier'>secrets</font> "
    "field (as opposed to its <font name='Courier'>environment</font> field, §2.7) tells the execution "
    "role to resolve each one from SSM at container startup and inject it as a real env var inside the "
    "running container — the app itself (<font name='Courier'>config.load_settings</font>) never knows "
    "or cares that some of its env vars came from SSM and others were set directly."
))

story.append(h2("1.5 The problem Terraform can't see on its own, and the fix"))
story.append(bl(
    "Terraform's whole reconciliation model (§0.1) depends on being able to tell when something "
    "changed. Two real things here change without Terraform noticing: pushing a new Docker image to "
    "the <i>same</i> tag (<font name='Courier'>:latest</font>) leaves the task definition's "
    "<font name='Courier'>image</font> string byte-for-byte identical; and an SSM "
    "<font name='Courier'>SecureString</font>'s <i>value</i> changing in place leaves its ARN — the "
    "only thing the task definition's <font name='Courier'>secrets</font> block references — "
    "unchanged too, and ECS only resolves secrets once, at container startup, so a running task "
    "wouldn't even notice if it did look. The content-hash <font name='Courier'>triggers</font> pattern "
    "(§0.8) is the fix for both: compute a hash of the actual thing that matters (source files; the "
    "secret values themselves) and use <i>that</i> as the signal a "
    "<font name='Courier'>null_resource</font> watches, sidestepping Terraform's normal "
    "attribute-diffing entirely."
))

story.append(rule())

# ---------------------------------------------------------------------------
# PART 2 — THIS REPO'S MODULE, FILE BY FILE
# ---------------------------------------------------------------------------
story.append(h1("Part 2 — This repo's module, file by file"))
layout_rows = [
    ["<b>File</b>", "<b>Role</b>"],
    ["infra/aws/ecs-fargate/main.tf", "Every resource -- ECR, Docker build/push, security groups, ALB, IAM, SSM secrets, ECS cluster/task/service, the force-redeploy trigger (419 lines)."],
    ["infra/aws/ecs-fargate/variables.tf", "Every input this module accepts -- deploy-shape knobs (region, cpu/memory) plus every connector's optional config (126 lines)."],
    ["infra/aws/ecs-fargate/outputs.tf", "The four values printed after apply -- service_url is the one you actually use."],
    ["infra/aws/ecs-fargate/terraform.tfvars.example", "Copy to terraform.tfvars (gitignored) and fill in; the template for real, local, un-committed values."],
]
story.append(simple_table(layout_rows, [2.3 * inch, USABLE_W - 2.3 * inch]))

story.append(h2("2.1 Provider block and the source-hash locals"))
story.append(code_block(
    "terraform {\n"
    "  required_version = \">= 1.5\"\n"
    "  required_providers {\n"
    "    aws = { source = \"hashicorp/aws\", version = \"~> 5.0\" }\n"
    "  }\n"
    "}\n\n"
    "provider \"aws\" { region = var.aws_region }\n\n"
    "locals {\n"
    "  repo_root = abspath(\"${path.module}/../../..\")\n"
    "  source_hash = sha1(join(\"\", [\n"
    "    for f in fileset(local.repo_root, \"src/**/*\") : filesha1(\"${local.repo_root}/${f}\")\n"
    "  ]))\n"
    "  dockerfile_hash = filesha1(\"${local.repo_root}/Dockerfile\")\n"
    "}\n"
))
story.append(bl(
    "<font name='Courier'>~&gt; 5.0</font> pins the AWS provider to the 5.x line — allows patch/minor "
    "upgrades, blocks an accidental breaking major-version jump. "
    "<font name='Courier'>path.module</font> is a built-in reference to the directory this "
    "<font name='Courier'>.tf</font> file lives in, letting <font name='Courier'>local.repo_root</font> "
    "walk back up to the actual repository root regardless of where "
    "<font name='Courier'>terraform apply</font> is run from. <font name='Courier'>source_hash</font> "
    "and <font name='Courier'>dockerfile_hash</font> are the values §1.5's fix depends on — computed "
    "once here, referenced by two different <font name='Courier'>null_resource</font>s later (§2.2, "
    "§2.8)."
))

story.append(h2("2.2 ECR + the Docker build/push escape hatch"))
story.append(code_block(
    "resource \"aws_ecr_repository\" \"this\" {\n"
    "  name         = var.app_name\n"
    "  force_delete = true\n"
    "}\n\n"
    "resource \"null_resource\" \"docker_build_push\" {\n"
    "  depends_on = [aws_ecr_repository.this]\n"
    "  triggers = {\n"
    "    source_hash     = local.source_hash\n"
    "    dockerfile_hash = local.dockerfile_hash\n"
    "    image_tag       = var.image_tag\n"
    "  }\n"
    "  provisioner \"local-exec\" {\n"
    "    interpreter = [\"bash\", \"-c\"]\n"
    "    working_dir = local.repo_root\n"
    "    command = replace(<<-EOT\n"
    "      aws ecr get-login-password --region ${var.aws_region} | docker login ...\n"
    "      docker buildx build --platform linux/amd64 \\\n"
    "        -t ${aws_ecr_repository.this.repository_url}:${var.image_tag} --push .\n"
    "    EOT\n"
    "    , \"\\r\\n\", \"\\n\")\n"
    "  }\n"
    "}\n"
))
story.append(bl(
    "<font name='Courier'>force_delete = true</font> lets <font name='Courier'>terraform destroy</font> "
    "remove the ECR repository even with images still in it, rather than failing and requiring a manual "
    "cleanup first. The <font name='Courier'>replace(..., \"\\r\\n\", \"\\n\")</font> wrapping the "
    "heredoc is a real, live-verified fix, not defensive boilerplate: on Windows with Git's default "
    "<font name='Courier'>core.autocrlf=true</font>, a checkout rewrites this file's line endings to "
    "CRLF, which corrupts the script by the time <font name='Courier'>bash</font> tries to run it — "
    "forcing LF here makes the script correct regardless of how the repo was checked out. "
    "<font name='Courier'>--platform linux/amd64</font> is there because Fargate only runs x86_64 — "
    "without it, running <font name='Courier'>apply</font> from an Apple Silicon or Windows-on-ARM "
    "machine would build an arm64 image that simply fails to start on Fargate."
))

story.append(h2("2.3 Security groups — two tiers, one direction of trust"))
story.append(code_block(
    "resource \"aws_security_group\" \"alb\" {\n"
    "  ingress { from_port = 80, to_port = 80, protocol = \"tcp\", cidr_blocks = [\"0.0.0.0/0\"] }\n"
    "  egress  { from_port = 0,  to_port = 0,  protocol = \"-1\",  cidr_blocks = [\"0.0.0.0/0\"] }\n"
    "}\n\n"
    "resource \"aws_security_group\" \"service\" {\n"
    "  ingress {\n"
    "    from_port       = 8000\n"
    "    to_port         = 8000\n"
    "    protocol        = \"tcp\"\n"
    "    security_groups = [aws_security_group.alb.id]   # NOT a cidr_blocks -- only the ALB, ever\n"
    "  }\n"
    "  egress { from_port = 0, to_port = 0, protocol = \"-1\", cidr_blocks = [\"0.0.0.0/0\"] }\n"
    "}\n"
))
story.append(bl(
    "The service security group's <font name='Courier'>ingress</font> references "
    "<i>another security group</i> (<font name='Courier'>aws_security_group.alb.id</font>) instead of "
    "a CIDR block — this is a live, dynamic membership check (\"traffic from something currently in the "
    "ALB security group\"), not a fixed IP range, and it's what actually enforces §1.3's claim that the "
    "task's public IP grants no direct access: nothing except the ALB's security group can reach port "
    "8000, full stop, regardless of source IP. Both groups' unrestricted "
    "<font name='Courier'>egress</font> is deliberately broad — the service needs outbound access to "
    "ECR, CloudWatch, SSM, and every external connector API (Gmail, Salesforce, Jira, and optionally "
    "Postgres), which is an open-ended set of destinations not worth enumerating for an MVP deploy."
))

story.append(h2("2.4 The load balancer, target group, and listener"))
story.append(code_block(
    "resource \"aws_lb\" \"this\" {\n"
    "  internal           = false\n"
    "  load_balancer_type = \"application\"\n"
    "  security_groups    = [aws_security_group.alb.id]\n"
    "  subnets            = data.aws_subnets.default.ids\n"
    "}\n\n"
    "resource \"aws_lb_target_group\" \"this\" {\n"
    "  port        = 8000\n"
    "  target_type = \"ip\"          # Fargate tasks are targeted by IP, not by EC2 instance id\n"
    "  health_check {\n"
    "    path = \"/health\", matcher = \"200\", interval = 15, timeout = 5\n"
    "    healthy_threshold = 2, unhealthy_threshold = 5\n"
    "  }\n"
    "}\n\n"
    "resource \"aws_lb_listener\" \"http\" {\n"
    "  load_balancer_arn = aws_lb.this.arn\n"
    "  port              = 80\n"
    "  default_action { type = \"forward\", target_group_arn = aws_lb_target_group.this.arn }\n"
    "}\n"
))
story.append(bl(
    "Three resources, one pipeline: the <font name='Courier'>aws_lb</font> is the load balancer itself "
    "(the thing with a public DNS name — §2.9's <font name='Courier'>service_url</font> output); the "
    "<font name='Courier'>listener</font> says \"accept HTTP on port 80\"; the "
    "<font name='Courier'>target_group</font> is who traffic actually forwards to, and owns the health "
    "check against <font name='Courier'>/health</font> that decides whether a task is considered "
    "healthy enough to receive traffic at all. <font name='Courier'>target_type = \"ip\"</font> matters "
    "specifically because Fargate has no persistent EC2 instance to target — each task gets an "
    "ephemeral IP, and the target group tracks tasks by that IP instead."
))

story.append(h2("2.5 IAM — an execution role, scoped narrowly"))
story.append(code_block(
    "resource \"aws_iam_role\" \"execution\" {\n"
    "  assume_role_policy = data.aws_iam_policy_document.execution_trust.json  # ecs-tasks.amazonaws.com\n"
    "}\n\n"
    "resource \"aws_iam_role_policy_attachment\" \"execution_managed\" {\n"
    "  role       = aws_iam_role.execution.name\n"
    "  policy_arn = \"arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy\"\n"
    "}\n\n"
    "data \"aws_iam_policy_document\" \"execution_ssm_read\" {\n"
    "  statement {\n"
    "    actions   = [\"ssm:GetParameters\"]\n"
    "    resources = local.ssm_secret_arns    # only THESE parameters, never ssm:* on everything\n"
    "  }\n"
    "}\n"
))
story.append(bl(
    "This is an <b>execution role</b> — what ECS itself uses to pull the image, write logs, and resolve "
    "<font name='Courier'>secrets</font>, distinct from a <b>task role</b> the running application code "
    "would use to call AWS APIs on its own behalf (this app makes no AWS API calls itself, so it has "
    "none). The AWS-managed <font name='Courier'>AmazonECSTaskExecutionRolePolicy</font> covers image "
    "pulls and log writes broadly, but grants no SSM access at all — the custom "
    "<font name='Courier'>execution_ssm_read</font> policy adds exactly one narrow permission "
    "(<font name='Courier'>ssm:GetParameters</font>) scoped to exactly the parameter ARNs this "
    "deployment actually created (<font name='Courier'>local.ssm_secret_arns</font>, §2.6), rather than "
    "a blanket <font name='Courier'>ssm:*</font> on <font name='Courier'>\"*\"</font> — a deliberate, "
    "minimal grant, not the path of least resistance."
))

story.append(h2("2.6 SSM secrets — three always, two conditional"))
story.append(code_block(
    "resource \"aws_ssm_parameter\" \"google_client_secret\" {\n"
    "  name  = \"/${var.app_name}/GOOGLE_CLIENT_SECRET\"\n"
    "  type  = \"SecureString\"\n"
    "  value = var.google_client_secret != \"\" ? var.google_client_secret : \"unset\"\n"
    "}\n"
    "# ...salesforce_client_secret, jira_api_token follow the same always-created shape\n\n"
    "resource \"aws_ssm_parameter\" \"database_url\" {\n"
    "  count = var.database_url != \"\" ? 1 : 0    # conditional -- see §0.6\n"
    "  name  = \"/${var.app_name}/DATABASE_URL\"\n"
    "  type  = \"SecureString\"\n"
    "  value = var.database_url\n"
    "}\n"
))
story.append(bl(
    "Two different treatments for two different kinds of \"empty.\" "
    "<font name='Courier'>google_client_secret</font>/<font name='Courier'>salesforce_client_secret</font>/"
    "<font name='Courier'>jira_api_token</font> are always created, falling back to the literal string "
    "<font name='Courier'>\"unset\"</font> when the variable is empty — harmless, because a real "
    "connector call would fail on an actually-invalid credential anyway, and simpler than making the "
    "parameter itself conditional. <font name='Courier'>google_token_json</font> and "
    "<font name='Courier'>database_url</font> use <font name='Courier'>count</font> instead, because "
    "an <font name='Courier'>\"unset\"</font> placeholder would be actively wrong for them: an empty "
    "<font name='Courier'>GOOGLE_TOKEN_JSON</font> env var should mean \"fall back to the interactive "
    "OAuth flow\" (google_auth.py, connector-layer doc §2.7), not \"here's a literal token string that "
    "happens to say 'unset'\"; and an empty <font name='Courier'>DATABASE_URL</font> should mean \"no "
    "Postgres configured, use the file-backed store\" (config.py's <font name='Courier'>load_settings</font>), "
    "not a connection string the app would actually try and fail to connect to."
))

story.append(h2("2.7 The ECS task definition and service"))
story.append(code_block(
    "resource \"aws_ecs_task_definition\" \"this\" {\n"
    "  requires_compatibilities = [\"FARGATE\"]\n"
    "  network_mode             = \"awsvpc\"\n"
    "  execution_role_arn       = aws_iam_role.execution.arn\n\n"
    "  container_definitions = jsonencode([{\n"
    "    name  = var.app_name\n"
    "    image = \"${aws_ecr_repository.this.repository_url}:${var.image_tag}\"\n"
    "    portMappings = [{ containerPort = 8000, protocol = \"tcp\" }]\n"
    "    environment = [\n"
    "      { name = \"GOOGLE_CLIENT_ID\", value = var.google_client_id },\n"
    "      { name = \"JIRA_BASE_URL\", value = var.jira_base_url },\n"
    "      # ...every other non-secret connector value\n"
    "    ]\n"
    "    secrets = local.container_secrets   # resolved from SSM at startup -- see §1.4, §2.6\n"
    "  }])\n"
    "}\n\n"
    "resource \"aws_ecs_service\" \"this\" {\n"
    "  depends_on      = [aws_lb_listener.http, null_resource.docker_build_push]\n"
    "  launch_type     = \"FARGATE\"\n"
    "  network_configuration {\n"
    "    subnets          = data.aws_subnets.default.ids\n"
    "    security_groups  = [aws_security_group.service.id]\n"
    "    assign_public_ip = true       # so the task can reach ECR/the internet -- see §1.3\n"
    "  }\n"
    "  load_balancer { target_group_arn = aws_lb_target_group.this.arn, container_port = 8000 }\n"
    "}\n"
))
story.append(bl(
    "The <font name='Courier'>environment</font> vs. <font name='Courier'>secrets</font> split on the "
    "container definition is §1.4's security boundary made concrete: every value in "
    "<font name='Courier'>environment</font> is a plain string right there in the task definition; "
    "every value in <font name='Courier'>secrets</font> is a <font name='Courier'>valueFrom</font> ARN "
    "reference the execution role resolves at startup. The service's explicit "
    "<font name='Courier'>depends_on</font> matters because Terraform's automatic dependency graph "
    "(§0.4) can't see everything here — the ECS service needs the listener to already exist (so its "
    "target group has somewhere to receive traffic from) and needs the Docker image already pushed "
    "(§2.2) before it tries to start a task from it, and neither of those is expressed through an "
    "attribute reference the graph would pick up automatically."
))

story.append(h2("2.8 force_new_deployment — closing the loop from §1.5"))
story.append(code_block(
    "resource \"null_resource\" \"force_new_deployment\" {\n"
    "  depends_on = [aws_ecs_service.this, null_resource.docker_build_push]\n"
    "  triggers = {\n"
    "    source_hash  = local.source_hash\n"
    "    secrets_hash = sha1(join(\"\", [\n"
    "      var.google_client_secret, var.google_token_json, var.salesforce_client_secret,\n"
    "      var.jira_api_token, var.database_url,\n"
    "    ]))\n"
    "  }\n"
    "  provisioner \"local-exec\" {\n"
    "    command = \"aws ecs update-service --force-new-deployment ...\"\n"
    "  }\n"
    "}\n"
))
story.append(bl(
    "This is where §1.5's problem actually gets closed: a new image at the same tag, or a changed "
    "secret <i>value</i>, is invisible to Terraform's normal change detection but very visible to this "
    "<font name='Courier'>null_resource</font>'s hashed <font name='Courier'>triggers</font> — when "
    "either changes, it re-runs <font name='Courier'>aws ecs update-service --force-new-deployment</font> "
    "directly via the AWS CLI, which tells ECS to stop the running task(s) and start fresh ones "
    "(re-pulling the image, re-resolving every secret). The result: a plain "
    "<font name='Courier'>terraform apply</font> after any source or secret change is enough on its own "
    "— no separate manual redeploy command, ever."
))

story.append(h2("2.9 variables.tf, outputs.tf, and terraform.tfvars"))
story.append(bl(
    "Every connector-specific <font name='Courier'>variable</font> defaults to an empty string — the "
    "Terraform-level mirror of an unfilled local <font name='Courier'>.env</font> (FastAPI doc's "
    "config-loading section): leaving one unset doesn't break "
    "<font name='Courier'>apply</font>, it just means that connector's <font name='Courier'>/tools/*</font> "
    "routes 503 once deployed, exactly like running locally with no credentials configured. Real values "
    "go in <font name='Courier'>terraform.tfvars</font> — gitignored, never committed — copied from the "
    "checked-in <font name='Courier'>terraform.tfvars.example</font> template. The four "
    "<font name='Courier'>output</font> values (§outputs.tf) are what <font name='Courier'>apply</font> "
    "prints at the end; <font name='Courier'>service_url</font> is the one actually used afterward — "
    "the public HTTP URL to point <font name='Courier'>scripts/api_smoke_test.py</font> or a real "
    "caller at."
))

story.append(rule())

# ---------------------------------------------------------------------------
# PART 3 — INFRASTRUCTURE-AS-CODE PATTERNS, NAMED
# ---------------------------------------------------------------------------
story.append(h1("Part 3 — Infrastructure-as-code patterns used here, named explicitly"))
patterns = [
    ["<b>Pattern</b>", "<b>Where</b>", "<b>What problem it actually solves here</b>"],
    ["Declarative desired-state reconciliation",
     "Every resource block; the whole init/plan/apply cycle (§0.1)",
     "Re-running apply with nothing changed does nothing -- infrastructure described once, safe to re-apply indefinitely."],
    ["Content-hash trigger",
     "local.source_hash/dockerfile_hash/secrets_hash driving two null_resources (§2.2, §2.8)",
     "Surfaces changes (new source code, a rotated secret) that Terraform's own attribute-diffing structurally can't see."],
    ["Escape hatch via null_resource + local-exec",
     "Docker build/push (§2.2); the forced ECS redeploy (§2.8)",
     "Lets an imperative action with no native Terraform resource type (running Docker, calling the AWS CLI directly) still live inside the declarative apply lifecycle."],
    ["Secrets via a dedicated store, not plain config",
     "SSM SecureString + the secrets/valueFrom split on the container definition (§1.4, §2.6, §2.7)",
     "Client secrets and API tokens are encrypted at rest and gated by an explicit IAM read permission -- a real boundary, not a convention."],
    ["Least-privilege IAM",
     "execution_ssm_read -- ssm:GetParameters scoped to local.ssm_secret_arns only (§2.5)",
     "The execution role can read exactly the parameters this deployment created, nothing else in the account's SSM store."],
    ["Defense in depth via security-group chaining",
     "aws_security_group.service's ingress references aws_security_group.alb.id, not a CIDR (§2.3)",
     "The task is reachable only from something currently in the ALB's security group -- a public IP existing grants no access on its own."],
    ["Conditional resource creation",
     "count = var.database_url != \"\" ? 1 : 0 (§0.6, §2.6)",
     "An optional secret (Postgres URL, a pre-consented OAuth token) is only created as an SSM parameter -- and only costs an IAM grant -- when actually configured."],
    ["Fail-open-to-safe defaults",
     "Every connector variable.tf entry defaults to \"\" (§2.9)",
     "A deployment with zero connectors configured still applies cleanly and passes its health check -- same MVP-friendly default as an unfilled local .env."],
]
story.append(simple_table(patterns, [1.7 * inch, 1.9 * inch, USABLE_W - 3.6 * inch]))

story.append(rule())

# ---------------------------------------------------------------------------
# PART 4 — INTERVIEW-PREP CHEAT SHEET
# ---------------------------------------------------------------------------
story.append(h1("Part 4 — Interview-prep Q&A"))
story.append(bl("Practice answering by pointing at the actual code, not reciting the definition."))

qa = [
    ("Q: What does 'declarative' actually mean here, concretely?",
     "A: You write what should exist (an ECR repo named X, a task with these env vars), not the steps "
     "to get there. Terraform compares that description against its state file, computes the gap "
     "against real AWS resources, and decides itself what to create/change/destroy. Run apply twice "
     "with nothing changed and the second run is a no-op -- that idempotence is the practical payoff "
     "(§0.1)."),
    ("Q: Terraform doesn't run your Docker build itself -- how does this module get an image built and "
     "pushed as part of `terraform apply`?",
     "A: null_resource.docker_build_push (§2.2) -- a resource with no AWS meaning of its own, used "
     "purely to attach a local-exec provisioner (an arbitrary bash script) to the apply lifecycle. Its "
     "triggers map (a hash of every tracked source file plus the Dockerfile) is what decides whether "
     "the provisioner actually re-runs on a given apply, rather than every single time."),
    ("Q: Two real changes here are invisible to Terraform's normal change detection. What are they, "
     "and how does this module handle both?",
     "A: A new image pushed to the same :latest tag -- the task definition's image string is textually "
     "unchanged. And an SSM SecureString's value changing in place -- its ARN, the only thing the task "
     "definition's secrets block references, doesn't change either, and ECS only resolves secrets once "
     "at task startup. Both are handled the same way: null_resource.force_new_deployment (§2.8) hashes "
     "the actual source/secret values as its trigger, and calls `aws ecs update-service "
     "--force-new-deployment` directly whenever that hash changes -- so a plain `terraform apply` alone "
     "is always enough, no manual follow-up command."),
    ("Q: Why does this module reuse the account's default VPC instead of creating a dedicated one, and "
     "what's the actual security tradeoff?",
     "A: A dedicated VPC for a task that needs outbound internet access (to pull its image, call "
     "external APIs) usually means private subnets plus a NAT Gateway, which costs roughly as much per "
     "month as the ALB itself -- not worth it for an MVP deploy. Instead the task runs in the default "
     "VPC's already-public subnets with its own public IP (assign_public_ip = true), and the actual "
     "access control is the security group: aws_security_group.service only allows inbound from "
     "aws_security_group.alb.id, not from any CIDR block, so having a public IP doesn't by itself grant "
     "reachability (§1.3, §2.3)."),
    ("Q: Walk through why a secret goes into the SSM `secrets` block instead of the task definition's "
     "plain `environment` list.",
     "A: environment values sit as plain text right in the task definition -- readable by anyone who "
     "can view it via the console or CLI. secrets instead references an SSM SecureString's ARN "
     "(valueFrom), which the execution role resolves at container startup only because it holds an "
     "explicit ssm:GetParameters grant scoped to exactly those parameter ARNs (§2.5) -- a real "
     "IAM-enforced boundary. GOOGLE_CLIENT_SECRET/SALESFORCE_CLIENT_SECRET/JIRA_API_TOKEN/"
     "GOOGLE_TOKEN_JSON/DATABASE_URL all go through secrets; GOOGLE_CLIENT_ID/JIRA_BASE_URL/etc. -- "
     "not sensitive on their own -- go through environment (§1.4, §2.7)."),
    ("Q: Why do google_client_secret/salesforce_client_secret/jira_api_token always get an SSM "
     "parameter (defaulting to the literal string \"unset\"), while google_token_json/database_url use "
     "count to skip creating one entirely when empty?",
     "A: Because an empty value means something different for each. An unconfigured client secret would "
     "fail a real API call regardless of what placeholder it holds, so \"unset\" is harmless filler. But "
     "an empty GOOGLE_TOKEN_JSON is supposed to mean 'fall back to the interactive OAuth flow', and an "
     "empty DATABASE_URL is supposed to mean 'use the file-backed store' -- in both cases a literal "
     "'unset' string would be actively wrong, read as a real (if broken) value instead of 'not "
     "configured'. count = var.x != \"\" ? 1 : 0 (§0.6, §2.6) skips creating the parameter at all in "
     "that case, matching what the app already treats an absent env var as."),
]
for q, a in qa:
    story.append(caption(q))
    story.append(bl(a))

story.append(Spacer(1, 10))
story.append(h1("Vocabulary cheat-sheet"))
vocab = [
    ["State file", "Terraform's record of what it last created, compared against your config on every plan/apply (§0.1)."],
    ["Provider", "A plugin (here, hashicorp/aws) that knows how to talk to one API/platform's resources."],
    ["Resource vs. data source", "resource creates/owns a thing; data only reads something that already exists (§0.3)."],
    ["Idempotent", "Re-running the same operation again changes nothing further -- true of both terraform apply and, separately, a connector's read methods (connector-layer doc, §1.4)."],
    ["null_resource + local-exec", "The escape hatch for running an arbitrary local command (Docker build, an AWS CLI call) inside Terraform's apply lifecycle (§0.8)."],
    ["Trigger", "A value null_resource watches -- when it changes between applies, the attached provisioner re-runs (§0.8)."],
    ["SSM Parameter Store / SecureString", "AWS's key-value config/secret store; SecureString encrypts the value at rest and gates reads by IAM permission (§1.4)."],
    ["ECS Fargate", "AWS's serverless container-running service -- describe a task definition, AWS finds the capacity to run it, no EC2 instance to manage (§1.2)."],
    ["ALB / target group / listener", "The load-balancer pipeline: the listener accepts traffic on a port, the target group tracks and health-checks the actual backends, the ALB is the public-facing object with a DNS name (§2.4)."],
    ["Execution role vs. task role", "The execution role is what ECS uses to start the container (pull image, resolve secrets, write logs); a task role -- unused here -- is what the running application code itself would use to call AWS APIs (§2.5)."],
]
vocab_rows = [["<b>Term</b>", "<b>Meaning here</b>"]] + vocab
vt_rows = [[Paragraph(f"<font name='Courier'><b>{esc(r[0])}</b></font>" if i > 0 else r[0], styles["tablecell"]),
            Paragraph(esc(r[1]) if i > 0 else r[1], styles["tablecell"])]
           for i, r in enumerate(vocab_rows)]
vt = Table(vt_rows, colWidths=[1.9 * inch, USABLE_W - 1.9 * inch])
vt.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), GRAY_FILL),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ("LINEBELOW", (0, 0), (-1, -1), 0.4, CODE_BORDER),
    ("BOX", (0, 0), (-1, -1), 0.8, CODE_BORDER),
]))
story.append(vt)

story.append(Spacer(1, 10))
story.append(bl(
    "That's the whole deployment: one Terraform module that builds and pushes an image, stands up a "
    "public ALB in front of a private Fargate task in the account's default VPC, keeps every connector "
    "secret in SSM behind a narrowly-scoped IAM role, and closes the two gaps in Terraform's own change "
    "detection with a pair of content-hashed null_resources — the same propose-then-reconcile shape as "
    "everything else in this codebase, just applied to infrastructure instead of a Gmail send."
))

OUT.parent.mkdir(parents=True, exist_ok=True)
doc = SimpleDocTemplate(
    str(OUT), pagesize=letter,
    leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=0.95 * inch,
    title="Deployment -- infra/aws/ecs-fargate/ (Terraform)",
)
DOC_FOOTER = footer("APM Connectors & Enterprise Systems — Terraform Deployment Reference")
doc.build(story, onFirstPage=DOC_FOOTER, onLaterPages=DOC_FOOTER)
print("wrote", OUT)
