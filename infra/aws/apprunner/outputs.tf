output "service_url" {
  description = "Public HTTPS URL of the deployed connector API."
  value       = "https://${aws_apprunner_service.this.service_url}"
}

output "ecr_repository_url" {
  description = "ECR repository the image is built and pushed to."
  value       = aws_ecr_repository.this.repository_url
}

output "apprunner_service_arn" {
  value = aws_apprunner_service.this.arn
}
