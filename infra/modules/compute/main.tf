# ECS services for the API and the worker. Permissions come from IAM task
# roles, so there are no access keys anywhere in the application.

locals {
  environment = [
    { name = "AWS_DEFAULT_REGION", value = var.region },
    { name = "SCAN_BUCKET", value = var.bucket_name },
    { name = "SCAN_TABLE", value = var.table_name },
    { name = "SCAN_QUEUE_URL", value = var.queue_url },
  ]
}

resource "aws_ecs_cluster" "main" {
  name = var.name
}

resource "aws_cloudwatch_log_group" "service" {
  for_each = toset(["api", "worker"])

  name              = "/ecs/${var.name}/${each.key}"
  retention_in_days = 7
}

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Used by ECS itself to pull images and write logs.
resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Each container gets only the actions its own code makes.
data "aws_iam_policy_document" "api" {
  statement {
    sid       = "StoreUploads"
    actions   = ["s3:PutObject", "s3:AbortMultipartUpload"]
    resources = ["${var.bucket_arn}/uploads/*"]
  }

  statement {
    sid       = "ReadFrames"
    actions   = ["s3:GetObject"]
    resources = ["${var.bucket_arn}/frames/*"]
  }

  statement {
    sid       = "QueueJobs"
    actions   = ["sqs:SendMessage"]
    resources = [var.queue_arn]
  }

  statement {
    sid       = "ManageScans"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [var.table_arn]
  }
}

data "aws_iam_policy_document" "worker" {
  statement {
    sid       = "ReadUploads"
    actions   = ["s3:GetObject"]
    resources = ["${var.bucket_arn}/uploads/*"]
  }

  statement {
    sid       = "StoreFrames"
    actions   = ["s3:PutObject", "s3:AbortMultipartUpload"]
    resources = ["${var.bucket_arn}/frames/*"]
  }

  statement {
    sid       = "ProcessJobs"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [var.queue_arn]
  }

  statement {
    sid       = "UpdateScans"
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [var.table_arn]
  }
}

resource "aws_iam_role" "api" {
  name               = "${var.name}-api"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy" "api" {
  name   = "application"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

resource "aws_iam_role" "worker" {
  name               = "${var.name}-worker"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy" "worker" {
  name   = "application"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker.json
}

# Lets ECS switch the load balancer between versions during a deployment.
data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "load_balancing" {
  name               = "${var.name}-ecs-load-balancing"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "load_balancing" {
  role       = aws_iam_role.load_balancing.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonECSInfrastructureRolePolicyForLoadBalancers"
}

resource "aws_security_group" "api" {
  name_prefix = "${var.name}-api-"
  description = "API tasks"
  vpc_id      = var.vpc_id

  ingress {
    description     = "From the load balancer"
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [var.alb_security_group_id]
  }

  egress {
    description = "VPC endpoints"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    description     = "S3 and DynamoDB gateway endpoints"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    prefix_list_ids = [var.s3_prefix_list_id, var.dynamodb_prefix_list_id]
  }

  lifecycle {
    create_before_destroy = true
  }

  tags = { Name = "${var.name}-api" }
}

resource "aws_security_group" "worker" {
  name_prefix = "${var.name}-worker-"
  description = "Worker tasks, which accept no inbound traffic"
  vpc_id      = var.vpc_id

  egress {
    description = "VPC endpoints"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    description     = "S3 and DynamoDB gateway endpoints"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    prefix_list_ids = [var.s3_prefix_list_id, var.dynamodb_prefix_list_id]
  }

  lifecycle {
    create_before_destroy = true
  }

  tags = { Name = "${var.name}-worker" }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.api.arn

  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([{
    name         = "api"
    image        = var.api_image
    essential    = true
    environment  = local.environment
    portMappings = [{ containerPort = 8080, protocol = "tcp" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.service["api"].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "api"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.worker.arn

  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([{
    name        = "worker"
    image       = var.worker_image
    essential   = true
    environment = local.environment
    # Gives a running scan time to finish when the task is stopped.
    stopTimeout = 120
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.service["worker"].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "worker"
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  name                 = "api"
  cluster              = aws_ecs_cluster.main.id
  task_definition      = aws_ecs_task_definition.api.arn
  desired_count        = var.api_desired_count
  launch_type          = "FARGATE"
  force_new_deployment = true

  # Terraform waits for the whole deployment, including the bake time.
  wait_for_steady_state = true

  deployment_configuration {
    strategy             = "BLUE_GREEN"
    bake_time_in_minutes = var.bake_time_minutes
  }

  # Rolls back if the new tasks never become healthy.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # Rolls back if the new tasks are healthy but start failing real requests.
  alarms {
    alarm_names = [var.rollback_alarm_name]
    enable      = true
    rollback    = true
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = "api"
    container_port   = 8080

    advanced_configuration {
      alternate_target_group_arn = var.green_target_group_arn
      production_listener_rule   = var.production_listener_rule_arn
      role_arn                   = aws_iam_role.load_balancing.arn
    }
  }

  # After each deployment ECS swaps which target group is live. Without this,
  # the next terraform apply would try to swap them back.
  lifecycle {
    ignore_changes = [load_balancer]
  }

  depends_on = [aws_iam_role_policy_attachment.load_balancing]
}

resource "aws_ecs_service" "worker" {
  name                 = "worker"
  cluster              = aws_ecs_cluster.main.id
  task_definition      = aws_ecs_task_definition.worker.arn
  desired_count        = var.worker_desired_count
  launch_type          = "FARGATE"
  force_new_deployment = true

  wait_for_steady_state = true

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.worker.id]
    assign_public_ip = false
  }
}
