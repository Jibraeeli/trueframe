# The HTTPS certificate is kept apart from the main stack. Certificates are
# free, and keeping this one means the DNS proof of ownership is only set up
# once, however many times the main stack is destroyed and rebuilt.

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
    key          = "trueframe/certificate.tfstate"
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
  description = "AWS region. Must match the load balancer's region."
  type        = string
  default     = "eu-west-2"
}

variable "domain_name" {
  description = "Domain to issue the certificate for"
  type        = string
}

resource "aws_acm_certificate" "main" {
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

output "certificate_arn" {
  value = aws_acm_certificate.main.arn
}

output "validation_record_name" {
  value = one(aws_acm_certificate.main.domain_validation_options).resource_record_name
}

output "validation_record_value" {
  value = one(aws_acm_certificate.main.domain_validation_options).resource_record_value
}
