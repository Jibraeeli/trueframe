output "alb_security_group_id" {
  value = aws_security_group.alb.id
}

output "target_group_arn" {
  value = aws_lb_target_group.api.arn
}

output "app_url" {
  value = local.https_enabled ? "https://${var.domain_name}" : "http://${aws_lb.main.dns_name}"
}

output "name_servers" {
  value = local.https_enabled ? aws_route53_zone.main[0].name_servers : []
}
