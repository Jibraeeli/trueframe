output "alb_security_group_id" {
  value = aws_security_group.alb.id
}

output "target_group_arn" {
  value = aws_lb_target_group.api.arn
}

output "green_target_group_arn" {
  value = aws_lb_target_group.api_green.arn
}

output "production_listener_rule_arn" {
  value = aws_lb_listener_rule.production.arn
}

output "rollback_alarm_name" {
  value = aws_cloudwatch_metric_alarm.api_errors.alarm_name
}

output "alb_dns_name" {
  value = aws_lb.main.dns_name
}

output "app_url" {
  value = local.https_enabled ? "https://${var.domain_name}" : "http://${aws_lb.main.dns_name}"
}

output "alb_arn_suffix" {
  value = aws_lb.main.arn_suffix
}
