output "alb_security_group_id" {
  value = aws_security_group.alb.id
}

output "target_group_arn" {
  value = aws_lb_target_group.api.arn
}

output "alb_dns_name" {
  value = aws_lb.main.dns_name
}

output "app_url" {
  value = local.https_enabled ? "https://${var.domain_name}" : "http://${aws_lb.main.dns_name}"
}
