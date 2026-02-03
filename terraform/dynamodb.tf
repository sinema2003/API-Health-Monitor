resource "aws_dynamodb_table" "endpoints" {
  name         = "${var.project_name}-endpoints"
  billing_mode = "PAY_PER_REQUEST"

  hash_key = "endpoint_id"

  attribute {
    name = "endpoint_id"
    type = "S"
  }

  # For scalable scheduling
  attribute {
    name = "schedule_bucket"
    type = "N"
  }

  attribute {
    name = "next_check_at"
    type = "N"
  }

  global_secondary_index {
    name            = "gsi_due_checks"
    hash_key        = "schedule_bucket"
    range_key       = "next_check_at"
    projection_type = "ALL"
  }
}
