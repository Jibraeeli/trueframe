# Lets GitHub Actions sign in to AWS without any stored access keys.
# GitHub issues a short-lived token for each run and AWS checks which
# repository and branch it came from before handing out temporary credentials.
#
# This stack stays up when the main stack is destroyed, and costs nothing.

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # The bucket name is passed in with -backend-config during terraform init.
  backend "s3" {
    key          = "trueframe/cicd.tfstate"
    region       = "eu-west-2"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "trueframe"
      ManagedBy = "terraform"
    }
  }
}

variable "region" {
  description = "AWS region the application is deployed to"
  type        = string
  default     = "eu-west-2"
}

variable "github_repository" {
  description = "Repository allowed to use these roles, as owner/name"
  type        = string
  default     = "Jibraeeli/trueframe"
}

data "aws_caller_identity" "current" {}

locals {
  account_id   = data.aws_caller_identity.current.account_id
  state_bucket = "arn:aws:s3:::trueframe-tfstate-${local.account_id}"
  role_prefix  = "arn:aws:iam::${local.account_id}:role/trueframe-"
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "trust_pull_requests" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:pull_request"]
    }
  }
}

data "aws_iam_policy_document" "trust_main_branch" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only workflows running from main can deploy. A branch or pull request
    # gets a different subject and is refused.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/main"]
    }
  }
}

# Pull requests can look but not change anything. terraform plan runs with
# -lock=false, so this role needs no write access to the state bucket.
resource "aws_iam_role" "plan" {
  name               = "trueframe-github-plan"
  assume_role_policy = data.aws_iam_policy_document.trust_pull_requests.json
}

resource "aws_iam_role_policy_attachment" "plan_read_only" {
  role       = aws_iam_role.plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# ReadOnlyAccess can read object contents, and user uploads are private.
data "aws_iam_policy_document" "plan_no_uploads" {
  statement {
    sid       = "NeverReadUserFiles"
    effect    = "Deny"
    actions   = ["s3:GetObject"]
    resources = ["arn:aws:s3:::trueframe-uploads-*/*"]
  }
}

resource "aws_iam_role_policy" "plan_no_uploads" {
  name   = "no-user-files"
  role   = aws_iam_role.plan.id
  policy = data.aws_iam_policy_document.plan_no_uploads.json
}

data "aws_iam_policy_document" "deploy" {
  statement {
    sid    = "BuildTheStack"
    effect = "Allow"
    #checkov:skip=CKV_AWS_107:Terraform has to manage these services in full. The statement is limited to one region and the role to the main branch.
    #checkov:skip=CKV_AWS_108:Terraform has to manage these services in full. The statement is limited to one region and the role to the main branch.
    #checkov:skip=CKV_AWS_109:Terraform has to manage these services in full. The statement is limited to one region and the role to the main branch.
    #checkov:skip=CKV_AWS_110:IAM changes are in a separate statement limited to trueframe roles.
    #checkov:skip=CKV_AWS_111:Terraform has to manage these services in full. The statement is limited to one region and the role to the main branch.
    #checkov:skip=CKV_AWS_356:Many of these actions cannot be limited by resource, and resource names are not known before creation.
    actions = [
      "cloudwatch:*",
      "dynamodb:*",
      "ec2:*",
      "ecr:*",
      "ecs:*",
      "elasticloadbalancing:*",
      "logs:*",
      "sqs:*",
      "wafv2:*",
    ]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.region]
    }
  }

  statement {
    sid       = "ManageApplicationBucket"
    actions   = ["s3:*"]
    resources = ["arn:aws:s3:::trueframe-uploads-*", "arn:aws:s3:::trueframe-uploads-*/*"]
  }

  statement {
    sid       = "FindTerraformState"
    actions   = ["s3:ListBucket"]
    resources = [local.state_bucket]
  }

  # Only the main stack's state, so a deploy cannot alter this stack or the
  # certificate's.
  statement {
    sid     = "UseTerraformState"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [
      "${local.state_bucket}/trueframe/terraform.tfstate",
      "${local.state_bucket}/trueframe/terraform.tfstate.tflock",
    ]
  }

  statement {
    sid = "ManageApplicationRoles"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:DeleteRolePolicy",
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
      "iam:ListRolePolicies",
      "iam:ListRoleTags",
      "iam:PutRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy",
    ]
    resources = ["${local.role_prefix}*"]
  }

  statement {
    sid       = "AttachOnlyKnownManagedPolicies"
    actions   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
    resources = ["${local.role_prefix}*"]

    condition {
      test     = "ArnEquals"
      variable = "iam:PolicyARN"
      values = [
        "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
        "arn:aws:iam::aws:policy/AmazonECSInfrastructureRolePolicyForLoadBalancers",
      ]
    }
  }

  statement {
    sid     = "HandRolesToEcsOnly"
    actions = ["iam:PassRole"]
    resources = [
      "${local.role_prefix}api",
      "${local.role_prefix}worker",
      "${local.role_prefix}execution",
      "${local.role_prefix}ecs-load-balancing",
    ]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com", "ecs.amazonaws.com"]
    }
  }

  statement {
    sid       = "AllowAwsServiceRoles"
    actions   = ["iam:CreateServiceLinkedRole"]
    resources = ["arn:aws:iam::${local.account_id}:role/aws-service-role/*"]

    condition {
      test     = "StringEquals"
      variable = "iam:AWSServiceName"
      values   = ["ecs.amazonaws.com", "elasticloadbalancing.amazonaws.com"]
    }
  }

  statement {
    sid       = "ReadCertificate"
    actions   = ["acm:DescribeCertificate", "acm:ListTagsForCertificate"]
    resources = ["arn:aws:acm:${var.region}:${local.account_id}:certificate/*"]
  }
}

resource "aws_iam_role" "deploy" {
  name               = "trueframe-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.trust_main_branch.json
}

resource "aws_iam_role_policy" "deploy" {
  name   = "deploy-trueframe"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}

output "plan_role_name" {
  value = aws_iam_role.plan.name
}

output "deploy_role_name" {
  value = aws_iam_role.deploy.name
}
