output "bucket_name" {
  value = aws_s3_bucket.uploads.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.uploads.arn
}

output "table_name" {
  value = aws_dynamodb_table.scans.name
}

output "table_arn" {
  value = aws_dynamodb_table.scans.arn
}

output "queue_url" {
  value = aws_sqs_queue.scans.url
}

output "queue_arn" {
  value = aws_sqs_queue.scans.arn
}

output "repository_urls" {
  value = { for key, repo in aws_ecr_repository.images : key => repo.repository_url }
}
