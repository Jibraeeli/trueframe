variable "name" {
  description = "Prefix for resource names"
  type        = string
  default     = "trueframe"
}

variable "region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "eu-west-2"
}

variable "domain_name" {
  description = "Domain the application is served from"
  type        = string
  default     = ""
}

variable "certificate_arn" {
  description = "Issued ACM certificate for the domain. Leave empty to serve plain HTTP."
  type        = string
  default     = ""
}

variable "image_tag" {
  description = "Image tag to run for both the API and the worker"
  type        = string
  default     = "unset"
}

variable "api_desired_count" {
  description = "Number of API tasks. Keep at 0 until images have been pushed."
  type        = number
  default     = 0
}

variable "worker_desired_count" {
  description = "Number of worker tasks. Keep at 0 until images have been pushed."
  type        = number
  default     = 0
}

variable "bake_time_minutes" {
  description = "How long the old API version is kept running after traffic moves, ready to roll back to"
  type        = number
  default     = 3
}

variable "endpoint_az_count" {
  description = "Availability zones that hold interface endpoints. 1 is cheaper, 2 survives a zone failure."
  type        = number
  default     = 1

  validation {
    condition     = contains([1, 2], var.endpoint_az_count)
    error_message = "endpoint_az_count must be 1 or 2."
  }
}
