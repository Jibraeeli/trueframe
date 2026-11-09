variable "name" {
  type = string
}

variable "region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "s3_prefix_list_id" {
  type = string
}

variable "dynamodb_prefix_list_id" {
  type = string
}

variable "alb_security_group_id" {
  type = string
}

variable "target_group_arn" {
  type = string
}

variable "api_image" {
  type = string
}

variable "worker_image" {
  type = string
}

variable "api_desired_count" {
  type = number
}

variable "worker_desired_count" {
  type = number
}

variable "bucket_name" {
  type = string
}

variable "bucket_arn" {
  type = string
}

variable "table_name" {
  type = string
}

variable "table_arn" {
  type = string
}

variable "queue_url" {
  type = string
}

variable "queue_arn" {
  type = string
}
