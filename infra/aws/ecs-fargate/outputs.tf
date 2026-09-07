output "service_url" {
  description = "Public HTTP URL of the deployed connector API."
  value       = "http://${aws_lb.this.dns_name}"
}

output "ecr_repository_url" {
  description = "ECR repository the image is built and pushed to."
  value       = aws_ecr_repository.this.repository_url
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "ecs_service_name" {
  value = aws_ecs_service.this.name
}
