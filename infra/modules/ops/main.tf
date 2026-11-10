# Scale to zero, custom metrics, alarms and the dashboard.

locals {
  namespace = "TrueFrame"

  # Fargate ARM in eu-west-2, in US dollars: 0.03725 per vCPU hour and 0.00409
  # per GB hour. The worker has 1 vCPU and 3 GB, and there are 3600 seconds in
  # an hour. This counts only the time spent on a scan, not idle time.
  worker_dollars_per_second = (0.03725 + 3 * 0.00409) / 3600

  worker_dimensions = ["ClusterName", var.cluster_name, "ServiceName", var.worker_service_name]
  api_dimensions    = ["ClusterName", var.cluster_name, "ServiceName", var.api_service_name]
  queue_dimensions  = ["QueueName", var.queue_name]
  dlq_dimensions    = ["QueueName", var.dead_letter_queue_name]
  alb_dimensions    = ["LoadBalancer", var.alb_arn_suffix]

  # Space-separated fields of the worker's log line, as written in main.py.
  scan_complete_pattern = "[date, time, level=INFO, logger, scan=Scan, id, state=complete, in, seconds, unit, after, queued_seconds, ...]"
}

# --- Scale to zero ---------------------------------------------------------

resource "aws_appautoscaling_target" "worker" {
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = "service/${var.cluster_name}/${var.worker_service_name}"
  min_capacity       = 0
  max_capacity       = var.worker_max_count
}

# Adds a worker while jobs are waiting. It repeats after each cooldown until
# the queue is drained or the maximum is reached.
resource "aws_appautoscaling_policy" "scale_out" {
  name               = "${var.name}-worker-scale-out"
  policy_type        = "StepScaling"
  service_namespace  = aws_appautoscaling_target.worker.service_namespace
  scalable_dimension = aws_appautoscaling_target.worker.scalable_dimension
  resource_id        = aws_appautoscaling_target.worker.resource_id

  step_scaling_policy_configuration {
    adjustment_type         = "ChangeInCapacity"
    cooldown                = 180
    metric_aggregation_type = "Maximum"

    step_adjustment {
      metric_interval_lower_bound = 0
      scaling_adjustment          = 1
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "scale_out" {
  alarm_name          = "${var.name}-worker-scale-out"
  alarm_description   = "Jobs are waiting on the queue, so a worker is needed"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_appautoscaling_policy.scale_out.arn]

  dimensions = {
    QueueName = var.queue_name
  }
}

# Removes every worker once nothing has been waiting or running for a while.
# In-flight messages are included so a worker is never removed mid-scan.
resource "aws_appautoscaling_policy" "scale_in" {
  name               = "${var.name}-worker-scale-in"
  policy_type        = "StepScaling"
  service_namespace  = aws_appautoscaling_target.worker.service_namespace
  scalable_dimension = aws_appautoscaling_target.worker.scalable_dimension
  resource_id        = aws_appautoscaling_target.worker.resource_id

  step_scaling_policy_configuration {
    adjustment_type         = "ExactCapacity"
    cooldown                = 60
    metric_aggregation_type = "Maximum"

    step_adjustment {
      metric_interval_upper_bound = 0
      scaling_adjustment          = 0
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "scale_in" {
  alarm_name          = "${var.name}-worker-scale-in"
  alarm_description   = "The queue has been empty, so workers can be removed"
  evaluation_periods  = var.idle_minutes_before_scale_in
  threshold           = 0
  comparison_operator = "LessThanOrEqualToThreshold"
  # An idle queue can stop reporting. No data means no work, not a fault.
  treat_missing_data = "breaching"
  alarm_actions      = [aws_appautoscaling_policy.scale_in.arn]

  metric_query {
    id          = "total"
    expression  = "visible + running"
    return_data = true
  }

  metric_query {
    id = "visible"

    metric {
      namespace   = "AWS/SQS"
      metric_name = "ApproximateNumberOfMessagesVisible"
      stat        = "Maximum"
      period      = 60
      dimensions = {
        QueueName = var.queue_name
      }
    }
  }

  metric_query {
    id = "running"

    metric {
      namespace   = "AWS/SQS"
      metric_name = "ApproximateNumberOfMessagesNotVisible"
      stat        = "Maximum"
      period      = 60
      dimensions = {
        QueueName = var.queue_name
      }
    }
  }
}

# --- Custom metrics, read from the worker's logs ----------------------------

resource "aws_cloudwatch_log_metric_filter" "scan_seconds" {
  name           = "${var.name}-scan-seconds"
  log_group_name = var.worker_log_group
  pattern        = local.scan_complete_pattern

  metric_transformation {
    namespace = local.namespace
    name      = "ScanSeconds"
    value     = "$seconds"
    unit      = "Seconds"
  }
}

resource "aws_cloudwatch_log_metric_filter" "queue_wait_seconds" {
  name           = "${var.name}-queue-wait-seconds"
  log_group_name = var.worker_log_group
  pattern        = local.scan_complete_pattern

  metric_transformation {
    namespace = local.namespace
    name      = "QueueWaitSeconds"
    value     = "$queued_seconds"
    unit      = "Seconds"
  }
}

resource "aws_cloudwatch_log_metric_filter" "malware" {
  name           = "${var.name}-malware-flagged"
  log_group_name = var.worker_log_group
  pattern        = "\"flagged as malware\""

  metric_transformation {
    namespace = local.namespace
    name      = "MalwareFlagged"
    value     = "1"
    unit      = "Count"
  }
}

resource "aws_cloudwatch_log_metric_filter" "worker_errors" {
  name           = "${var.name}-worker-errors"
  log_group_name = var.worker_log_group
  pattern        = "[date, time, level=ERROR, ...]"

  metric_transformation {
    namespace = local.namespace
    name      = "WorkerErrors"
    value     = "1"
    unit      = "Count"
  }
}

# --- Alarms that email a person ----------------------------------------------

resource "aws_cloudwatch_metric_alarm" "dead_letters" {
  alarm_name          = "${var.name}-dead-letters"
  alarm_description   = "A scan failed three times and was moved to the dead-letter queue"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alert_topic_arn]

  dimensions = {
    QueueName = var.dead_letter_queue_name
  }
}

# Set well above a normal cold start, which also shows up as queue age.
resource "aws_cloudwatch_metric_alarm" "queue_stuck" {
  alarm_name          = "${var.name}-queue-stuck"
  alarm_description   = "The oldest job has waited over 15 minutes, so workers are not keeping up"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 900
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alert_topic_arn]

  dimensions = {
    QueueName = var.queue_name
  }
}

resource "aws_cloudwatch_metric_alarm" "worker_errors" {
  alarm_name          = "${var.name}-worker-errors"
  alarm_description   = "The worker logged three or more errors in five minutes"
  namespace           = local.namespace
  metric_name         = aws_cloudwatch_log_metric_filter.worker_errors.metric_transformation[0].name
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alert_topic_arn]
}

# Errors the load balancer creates itself, such as having no healthy API task.
resource "aws_cloudwatch_metric_alarm" "api_unreachable" {
  alarm_name          = "${var.name}-api-unreachable"
  alarm_description   = "The load balancer could not get an answer from the API"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_ELB_5XX_Count"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alert_topic_arn]

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
  }
}

# --- Dashboard ---------------------------------------------------------------

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = var.name

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "alarm"
        x      = 0
        y      = 0
        width  = 24
        height = 2
        properties = {
          title = "Alarms"
          alarms = [
            aws_cloudwatch_metric_alarm.dead_letters.arn,
            aws_cloudwatch_metric_alarm.queue_stuck.arn,
            aws_cloudwatch_metric_alarm.worker_errors.arn,
            aws_cloudwatch_metric_alarm.api_unreachable.arn,
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 2
        width  = 12
        height = 6
        properties = {
          title  = "Scan time and time waiting for a worker (seconds)"
          region = var.region
          view   = "timeSeries"
          period = 60
          metrics = [
            [local.namespace, "ScanSeconds", { stat = "Average", label = "Scan, average" }],
            ["...", { stat = "p95", label = "Scan, 95th percentile" }],
            [local.namespace, "QueueWaitSeconds", { stat = "Maximum", label = "Longest wait in queue" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 2
        width  = 12
        height = 6
        properties = {
          title  = "Scans finished and malware rejected"
          region = var.region
          view   = "timeSeries"
          stat   = "Sum"
          period = 300
          metrics = [
            [local.namespace, "ScanSeconds", { stat = "SampleCount", label = "Scans finished" }],
            [local.namespace, "MalwareFlagged", { label = "Malware rejected" }],
            [local.namespace, "WorkerErrors", { label = "Worker errors" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 8
        width  = 12
        height = 6
        properties = {
          title  = "Queue and running workers"
          region = var.region
          view   = "timeSeries"
          stat   = "Maximum"
          period = 60
          metrics = [
            concat(["AWS/SQS", "ApproximateNumberOfMessagesVisible"], local.queue_dimensions, [{ label = "Waiting" }]),
            concat(["AWS/SQS", "ApproximateNumberOfMessagesNotVisible"], local.queue_dimensions, [{ label = "Being scanned" }]),
            concat(["AWS/SQS", "ApproximateNumberOfMessagesVisible"], local.dlq_dimensions, [{ label = "Dead letters" }]),
            # ECS reports one CPU sample per running task each minute.
            concat(["AWS/ECS", "CPUUtilization"], local.worker_dimensions, [{ stat = "SampleCount", label = "Running workers" }]),
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 8
        width  = 12
        height = 6
        properties = {
          title  = "Estimated worker compute cost per scan (US dollars)"
          region = var.region
          view   = "timeSeries"
          period = 300
          metrics = [
            [{ expression = "m1 * ${local.worker_dollars_per_second}", label = "Cost per scan", id = "cost" }],
            [local.namespace, "ScanSeconds", { stat = "Average", id = "m1", visible = false }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 14
        width  = 12
        height = 6
        properties = {
          title  = "Memory and CPU, highest task (%)"
          region = var.region
          view   = "timeSeries"
          stat   = "Maximum"
          period = 60
          yAxis  = { left = { min = 0, max = 100 } }
          metrics = [
            concat(["AWS/ECS", "MemoryUtilization"], local.worker_dimensions, [{ label = "Worker memory" }]),
            concat(["AWS/ECS", "CPUUtilization"], local.worker_dimensions, [{ label = "Worker CPU" }]),
            concat(["AWS/ECS", "MemoryUtilization"], local.api_dimensions, [{ label = "API memory" }]),
            concat(["AWS/ECS", "CPUUtilization"], local.api_dimensions, [{ label = "API CPU" }]),
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 14
        width  = 12
        height = 6
        properties = {
          title  = "API requests, errors and response time"
          region = var.region
          view   = "timeSeries"
          period = 60
          metrics = [
            concat(["AWS/ApplicationELB", "RequestCount"], local.alb_dimensions, [{ stat = "Sum", label = "Requests" }]),
            concat(["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count"], local.alb_dimensions, [{ stat = "Sum", label = "API 5xx" }]),
            concat(["AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count"], local.alb_dimensions, [{ stat = "Sum", label = "Load balancer 5xx" }]),
            concat(["AWS/ApplicationELB", "TargetResponseTime"], local.alb_dimensions, [{ stat = "p95", label = "Response time p95 (s)", yAxis = "right" }]),
          ]
        }
      },
    ]
  })
}
