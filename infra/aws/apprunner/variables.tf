variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "app_name" {
  description = "Name used for the ECR repository, App Runner service, and IAM roles."
  type        = string
  default     = "apm-connectors"
}

variable "image_tag" {
  description = "Tag to build, push, and deploy."
  type        = string
  default     = "latest"
}

variable "cpu" {
  description = "App Runner instance vCPU, e.g. \"0.25 vCPU\", \"1 vCPU\"."
  type        = string
  default     = "0.25 vCPU"
}

variable "memory" {
  description = "App Runner instance memory, e.g. \"0.5 GB\", \"2 GB\"."
  type        = string
  default     = "0.5 GB"
}

# -- Optional connector configuration -------------------------------------
# All optional and empty by default -- exactly like an unfilled-in local
# .env (see .env.example at the repo root): a connector left unset just
# means its /tools/* routes 503 until you configure it. Set the ones you
# want live in terraform.tfvars (never commit that file -- see
# terraform.tfvars.example).

variable "google_client_id" {
  description = "Google OAuth client ID, for Gmail + Calendar."
  type        = string
  default     = ""
}

variable "google_client_secret" {
  description = "Google OAuth client secret, for Gmail + Calendar. Stored as an SSM SecureString, never a plain env var."
  type        = string
  default     = ""
  sensitive   = true
}

variable "ms_graph_client_id" {
  description = "Microsoft Graph app registration client ID, for the OneDrive/SharePoint Excel connector."
  type        = string
  default     = ""
}

variable "ms_graph_client_secret" {
  description = "Microsoft Graph app registration client secret. Stored as an SSM SecureString, never a plain env var."
  type        = string
  default     = ""
  sensitive   = true
}

variable "ms_graph_tenant_id" {
  description = "Microsoft Graph tenant ID."
  type        = string
  default     = ""
}

variable "apm_excel_workbook_path" {
  description = "Local path (inside the container) to an Excel workbook, if using the local-file Excel connector. Usually left unset in favor of apm_excel_drive_file_id for a cloud deployment, since the container filesystem is ephemeral."
  type        = string
  default     = ""
}

variable "apm_excel_drive_file_id" {
  description = "Google Drive file id or name of the Excel workbook, if using the Drive-backed Excel connector."
  type        = string
  default     = ""
}
