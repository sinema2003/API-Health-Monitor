variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "project_name" {
  type    = string
  default = "hyperverge-health-monitor"
}

variable "sns_email" {
  type        = string
  description = "Email address to receive alerts"
}

variable "image_tag" {
  type    = string
  default = "latest"
}

variable "schedule_expression" {
  type    = string
  default = "rate(1 minute)"
}

variable "bucket_count" {
  type    = number
  default = 16
}

# A single task can process a subset of buckets: "0-3", "4-7", etc.
variable "bucket_start" {
  type    = number
  default = 0
}

variable "bucket_end" {
  type    = number
  default = 15
}
