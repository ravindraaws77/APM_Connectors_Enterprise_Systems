# AWS App Runner deployment for the connector API (Dockerfile at repo
# root). See docs/deployment.md for the runbook. This module:
#   1. creates an ECR repository,
#   2. builds & pushes the Docker image into it (local-exec: needs
#      Docker and the AWS CLI available wherever `terraform apply` runs),
#   3. stores the two OAuth client secrets in SSM Parameter Store
#      (SecureString) rather than as plain env vars,
#   4. stands up the App Runner service itself, reading the image from
#      ECR and the two secrets from SSM at container start.
#
# Nothing here is hooked up unless you fill in `terraform.tfvars` --
# every connector env var defaults to empty, same as an unconfigured
# local `.env`, so the corresponding /tools/* routes just 503 until you
# set one.

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

# -- ECR ----------------------------------------------------------------

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
    working_dir = local.repo_root
    command     = <<-EOT
      set -euo pipefail
      aws ecr get-login-password --region ${var.aws_region} \
        | docker login --username AWS --password-stdin ${aws_ecr_repository.this.repository_url}
      docker build -t ${aws_ecr_repository.this.repository_url}:${var.image_tag} .
      docker push ${aws_ecr_repository.this.repository_url}:${var.image_tag}
    EOT
  }
}

# -- IAM ------------------------------------------------------------------

# Lets App Runner's build/deploy machinery pull the image from ECR.
data "aws_iam_policy_document" "apprunner_build_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["build.apprunner.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "apprunner_access" {
  name               = "${var.app_name}-apprunner-access"
  assume_role_policy = data.aws_iam_policy_document.apprunner_build_trust.json
}

resource "aws_iam_role_policy_attachment" "apprunner_ecr_access" {
  role       = aws_iam_role.apprunner_access.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}

# Lets the running container itself read the two secrets from SSM at
# startup (App Runner's `runtime_environment_secrets`).
data "aws_iam_policy_document" "apprunner_instance_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["tasks.apprunner.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "apprunner_instance" {
  name               = "${var.app_name}-apprunner-instance"
  assume_role_policy = data.aws_iam_policy_document.apprunner_instance_trust.json
}

data "aws_iam_policy_document" "apprunner_instance_ssm_read" {
  statement {
    actions = ["ssm:GetParameters"]
    resources = [
      aws_ssm_parameter.google_client_secret.arn,
      aws_ssm_parameter.ms_graph_client_secret.arn,
    ]
  }
}

resource "aws_iam_role_policy" "apprunner_instance_ssm_read" {
  name   = "${var.app_name}-ssm-read"
  role   = aws_iam_role.apprunner_instance.id
  policy = data.aws_iam_policy_document.apprunner_instance_ssm_read.json
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

# -- App Runner service ----------------------------------------------------

resource "aws_apprunner_service" "this" {
  depends_on   = [null_resource.docker_build_push]
  service_name = var.app_name

  source_configuration {
    # So a later `terraform apply` that rebuilds/pushes a new image at
    # the same tag (see null_resource.docker_build_push above) actually
    # reaches production -- App Runner polls the image and redeploys on
    # its own, no extra `aws apprunner start-deployment` call needed.
    auto_deployments_enabled = true

    authentication_configuration {
      access_role_arn = aws_iam_role.apprunner_access.arn
    }

    image_repository {
      image_repository_type = "ECR"
      image_identifier      = "${aws_ecr_repository.this.repository_url}:${var.image_tag}"

      image_configuration {
        port = "8000"

        runtime_environment_variables = {
          GOOGLE_CLIENT_ID        = var.google_client_id
          MS_GRAPH_CLIENT_ID      = var.ms_graph_client_id
          MS_GRAPH_TENANT_ID      = var.ms_graph_tenant_id
          APM_EXCEL_WORKBOOK_PATH = var.apm_excel_workbook_path
          APM_EXCEL_DRIVE_FILE_ID = var.apm_excel_drive_file_id
        }

        runtime_environment_secrets = {
          GOOGLE_CLIENT_SECRET   = aws_ssm_parameter.google_client_secret.arn
          MS_GRAPH_CLIENT_SECRET = aws_ssm_parameter.ms_graph_client_secret.arn
        }
      }
    }
  }

  instance_configuration {
    cpu               = var.cpu
    memory            = var.memory
    instance_role_arn = aws_iam_role.apprunner_instance.arn
  }

  health_check_configuration {
    protocol            = "HTTP"
    path                = "/health"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 1
    unhealthy_threshold = 5
  }
}
