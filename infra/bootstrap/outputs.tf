output "state_bucket" {
  description = "Name of the bucket holding Terraform state"
  value       = aws_s3_bucket.state.bucket
}
