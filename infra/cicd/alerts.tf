# These stay when the application is destroyed. A budget has to keep watching
# after a teardown, because that is when a forgotten resource would go unnoticed.

variable "alert_email" {
  description = "Where alarms and budget warnings are sent. Not stored in this repository."
  type        = string
}

variable "monthly_budget_dollars" {
  type    = number
  default = 15
}

# The main stack's alarms send to this topic by name, so the email address only
# has to be confirmed once rather than after every deploy.
resource "aws_sns_topic" "alerts" {
  #checkov:skip=CKV_AWS_26:CloudWatch alarms cannot publish to a topic using the AWS-managed key, and the messages only name an alarm.
  name = "trueframe-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_budgets_budget" "usage" {
  name         = "trueframe-usage"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_dollars)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Credits are left out, otherwise they cancel the spending out and the
  # budget would stay at zero until the credits ran out.
  cost_types {
    include_credit = false
    include_refund = false
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
