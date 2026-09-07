# ECS on Fargate deployment for the connector API (Dockerfile at repo
# root), behind an Application Load Balancer. Replaces infra/aws/apprunner
# -- App Runner stopped accepting new customers (AWS notice, effective
# 2026-04-30); this is the direct, mature-and-well-supported replacement.
# See docs/deployment.md for the runbook. This module:
#   1. creates an ECR repository, and builds/pushes the image into it
#      (local-exec: needs Docker and the AWS CLI on the machine running
#      `terraform apply`),
#   2. stores the two OAuth client secrets in SSM Parameter Store
#      (SecureString) rather than as plain env vars,
#   3. runs the image as an ECS Fargate service in the account's default
#      VPC, fronted by a public Application Load Balancer that health
#      -checks /health.
#
# Nothing here is hooked up unless you fill in `terraform.tfvars` --
# every connector env var defaults to empty, same as an unconfigured
# local `.env`, so the corresponding /tools/* routes just 503 until you
# set one.
#
# Uses the account's default VPC/subnets to avoid standing up a whole
# network from scratch for an MVP deploy. Its subnets are public by
# default (route to an Internet Gateway), so the task gets a public IP
# to pull its image from ECR -- no NAT Gateway needed (that alone would
# roughly double this deploy's monthly cost for no benefit here). This
# means the container is directly reachable if its security group
# allowed it -- it doesn't: only the ALB's security group may reach it,
# on the container port, so the public IP alone grants no direct access.

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  repo_root = abspath("${path.module}/../../..")
  # Re-run the docker build/push whenever the app source or Dockerfile
  # changes -- a simple content hash keyed off every tracked source file.
  source_hash = sha1(join("", [
    for f in fileset(local.repo_root, "src/**/*") : filesha1("${local.repo_root}/${f}")
  ]))
  dockerfile_hash = filesha1("${local.repo_root}/Dockerfile")
}

# -- Default VPC / subnets ------------------------------------------------

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# -- ECR ------------------------------------------------------------------

resource "aws_ecr_repository" "this" {
  name                 = var.app_name
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "null_resource" "docker_build_push" {
  depends_on = [aws_ecr_repository.this]

  triggers = {
    source_hash     = local.source_hash
    dockerfile_hash = local.dockerfile_hash
    image_tag       = var.image_tag
  }

  provisioner "local-exec" {
    # Requires bash (Git Bash / WSL on Windows, native on macOS/Linux) --
    # local-exec defaults to cmd.exe on Windows, which can't run this
    # script. See docs/deployment.md.
    interpreter = ["bash", "-c"]
    working_dir = local.repo_root
    # replace(...,"\r\n","\n"): on Windows, a checkout with the default
    # core.autocrlf=true rewrites this heredoc's line endings to CRLF,
    # which corrupts the script when bash runs it. Force LF regardless
    # of how the file was checked out. See .gitattributes.
    command = replace(<<-EOT
      set -euo pipefail
      aws ecr get-login-password --region ${var.aws_region} \
        | docker login --username AWS --password-stdin ${aws_ecr_repository.this.repository_url}
      # --platform linux/amd64: Fargate only runs x86_64 (this variant
      # of the module doesn't use Graviton/ARM task definitions), so
      # this cross-compiles even when `terraform apply` runs on an ARM
      # machine (Apple Silicon, Windows-on-ARM) where a plain
      # `docker build` would otherwise produce an arm64 image.
      docker buildx build --platform linux/amd64 \
        -t ${aws_ecr_repository.this.repository_url}:${var.image_tag} \
        --push .
    EOT
    , "\r\n", "\n")
  }
}

# -- Security groups --------------------------------------------------------

resource "aws_security_group" "alb" {
  name        = "${var.app_name}-alb"
  description = "Public ALB for ${var.app_name}"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP from anywhere"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "service" {
  name        = "${var.app_name}-service"
  description = "ECS service for ${var.app_name} -- only reachable from the ALB"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "From the ALB only"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    # Outbound needed for: pulling the image from ECR, pushing logs to
    # CloudWatch, reading secrets from SSM, and the app itself calling
    # Gmail/Calendar/Graph/Salesforce APIs.
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# -- Load balancer ----------------------------------------------------------

resource "aws_lb" "this" {
  name               = var.app_name
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = data.aws_subnets.default.ids
}

resource "aws_lb_target_group" "this" {
  name        = var.app_name
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.default.id
  target_type = "ip"

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 5
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }
}

# -- Logs ---------------------------------------------------------------

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.app_name}"
  retention_in_days = 14
}

# -- IAM ------------------------------------------------------------------

# The execution role: what ECS itself uses to pull the image, write
# logs, and resolve the `secrets` block below via SSM -- distinct from
# a task role (which the *app* would use to call AWS APIs; this app
# doesn't need one).
data "aws_iam_policy_document" "execution_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.app_name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.execution_trust.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_ssm_read" {
  statement {
    actions   = ["ssm:GetParameters"]
    resources = local.ssm_secret_arns
  }
}

resource "aws_iam_role_policy" "execution_ssm_read" {
  name   = "${var.app_name}-ssm-read"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_ssm_read.json
}

# -- Secrets (SSM Parameter Store, SecureString) --------------------------

resource "aws_ssm_parameter" "google_client_secret" {
  name  = "/${var.app_name}/GOOGLE_CLIENT_SECRET"
  type  = "SecureString"
  value = var.google_client_secret != "" ? var.google_client_secret : "unset"
}

resource "aws_ssm_parameter" "ms_graph_client_secret" {
  name  = "/${var.app_name}/MS_GRAPH_CLIENT_SECRET"
  type  = "SecureString"
  value = var.ms_graph_client_secret != "" ? var.ms_graph_client_secret : "unset"
}

resource "aws_ssm_parameter" "salesforce_client_secret" {
  name  = "/${var.app_name}/SALESFORCE_CLIENT_SECRET"
  type  = "SecureString"
  value = var.salesforce_client_secret != "" ? var.salesforce_client_secret : "unset"
}

# Only created when set -- unlike the two secrets above, this one has no
# "unset" placeholder: an unconfigured GOOGLE_TOKEN_JSON should mean the
# app falls back to the interactive/local-file flow (src/apm_connectors/
# tools/google_auth.py), the same as an unfilled local .env, not receive
# a literal "unset" string as a token.
resource "aws_ssm_parameter" "google_token_json" {
  count = var.google_token_json != "" ? 1 : 0
  name  = "/${var.app_name}/GOOGLE_TOKEN_JSON"
  type  = "SecureString"
  value = var.google_token_json
}

locals {
  ssm_secret_arns = concat(
    [
      aws_ssm_parameter.google_client_secret.arn,
      aws_ssm_parameter.ms_graph_client_secret.arn,
      aws_ssm_parameter.salesforce_client_secret.arn,
    ],
    var.google_token_json != "" ? [aws_ssm_parameter.google_token_json[0].arn] : []
  )

  container_secrets = concat(
    [
      { name = "GOOGLE_CLIENT_SECRET", valueFrom = aws_ssm_parameter.google_client_secret.arn },
      { name = "MS_GRAPH_CLIENT_SECRET", valueFrom = aws_ssm_parameter.ms_graph_client_secret.arn },
      { name = "SALESFORCE_CLIENT_SECRET", valueFrom = aws_ssm_parameter.salesforce_client_secret.arn },
    ],
    var.google_token_json != "" ? [{ name = "GOOGLE_TOKEN_JSON", valueFrom = aws_ssm_parameter.google_token_json[0].arn }] : []
  )
}

# -- ECS --------------------------------------------------------------------

resource "aws_ecs_cluster" "this" {
  name = var.app_name
}

resource "aws_ecs_task_definition" "this" {
  family                   = var.app_name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn

  container_definitions = jsonencode([
    {
      name  = var.app_name
      image = "${aws_ecr_repository.this.repository_url}:${var.image_tag}"
      portMappings = [
        { containerPort = 8000, protocol = "tcp" }
      ]
      environment = [
        { name = "GOOGLE_CLIENT_ID", value = var.google_client_id },
        { name = "MS_GRAPH_CLIENT_ID", value = var.ms_graph_client_id },
        { name = "MS_GRAPH_TENANT_ID", value = var.ms_graph_tenant_id },
        { name = "APM_EXCEL_WORKBOOK_PATH", value = var.apm_excel_workbook_path },
        { name = "APM_EXCEL_DRIVE_FILE_ID", value = var.apm_excel_drive_file_id },
        { name = "SALESFORCE_CLIENT_ID", value = var.salesforce_client_id },
        { name = "SALESFORCE_DOMAIN", value = var.salesforce_domain },
        { name = "SALESFORCE_API_VERSION", value = var.salesforce_api_version },
      ]
      secrets = local.container_secrets
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.this.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = var.app_name
        }
      }
    }
  ])
}

resource "aws_ecs_service" "this" {
  depends_on      = [aws_lb_listener.http, null_resource.docker_build_push]
  name            = var.app_name
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.this.arn
    container_name   = var.app_name
    container_port   = 8000
  }
}

# Two things Terraform's normal change detection can't see, both of
# which leave a stale, already-running task in place unless something
# explicitly forces a redeploy:
#   1. A new image pushed to the same ":latest" tag in ECR
#      (null_resource.docker_build_push re-running) -- the task
#      definition's `image` string is unchanged, so nothing about it
#      looks different to Terraform.
#   2. An SSM SecureString's *value* changing in place -- its ARN,
#      which is all the task definition's `secrets` block references,
#      doesn't change either. ECS also only resolves `secrets` once,
#      at task startup, so an already-running task never re-reads it
#      even if you did notice and go looking.
# Force a fresh deployment whenever either happens, so `terraform
# apply` alone is enough -- no separate manual `aws ecs update-service
# --force-new-deployment` step for either case.
resource "null_resource" "force_new_deployment" {
  depends_on = [aws_ecs_service.this, null_resource.docker_build_push]

  triggers = {
    source_hash     = local.source_hash
    dockerfile_hash = local.dockerfile_hash
    secrets_hash = sha1(join("", [
      var.google_client_secret,
      var.ms_graph_client_secret,
      var.google_token_json,
      var.salesforce_client_secret,
    ]))
  }

  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command = replace(<<-EOT
      set -euo pipefail
      aws ecs update-service --region ${var.aws_region} \
        --cluster ${aws_ecs_cluster.this.name} \
        --service ${aws_ecs_service.this.name} \
        --force-new-deployment >/dev/null
    EOT
    , "\r\n", "\n")
  }
}
