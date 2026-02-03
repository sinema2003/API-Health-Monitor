output "ecr_repo_url" {
  value = aws_ecr_repository.repo.repository_url
}

output "dynamodb_table_name" {
  value = aws_dynamodb_table.endpoints.name
}

output "sns_topic_arn" {
  value = aws_sns_topic.alerts.arn
}
output "dynamodb_gsi_name" {
  value = "gsi_due_checks"
}
