variable "name" {
  type = string
}

variable "region" {
  type = string
}

variable "cluster_name" {
  type = string
}

variable "api_service_name" {
  type = string
}

variable "worker_service_name" {
  type = string
}

variable "worker_log_group" {
  type = string
}

variable "queue_name" {
  type = string
}

variable "dead_letter_queue_name" {
  type = string
}

variable "alb_arn_suffix" {
  type = string
}

variable "alert_topic_arn" {
  type = string
}

variable "worker_max_count" {
  type = number
}

variable "idle_minutes_before_scale_in" {
  type = number
}
