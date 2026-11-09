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

output "name_servers" {
  description = "Set these at your domain registrar when using a domain"
  value       = module.edge.name_servers
}
