output "app_url" {
  description = "Address of the application"
  value       = module.edge.app_url
}

output "api_repository_url" {
  description = "ECR repository for the API image"
  value       = module.storage.repository_urls["api"]
}

output "worker_repository_url" {
  description = "ECR repository for the worker image"
  value       = module.storage.repository_urls["worker"]
}

output "alb_dns_name" {
  description = "Point the domain's CNAME record at this address"
  value       = module.edge.alb_dns_name
}
