resource "aws_ecr_repository" "repo" {
  name = "${var.project_name}-repo"
}

resource "aws_cloudwatch_log_group" "lg" {
  name              = "/ecs/${var.project_name}"
  retention_in_days = 3
}

resource "aws_ecs_cluster" "cluster" {
  name = "${var.project_name}-cluster"
}

resource "aws_security_group" "task_sg" {
  name        = "${var.project_name}-task-sg"
  description = "Egress-only SG for ECS task"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

locals {
  image_uri = "${aws_ecr_repository.repo.repository_url}:${var.image_tag}"
}

resource "aws_ecs_task_definition" "task" {
  family                   = "${var.project_name}-task"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = local.image_uri
      essential = true
      environment = [
        { name = "AWS_REGION",      value = var.region },
        { name = "DDB_TABLE_NAME",  value = aws_dynamodb_table.endpoints.name },
        { name = "SNS_TOPIC_ARN",   value = aws_sns_topic.alerts.arn },
        { name = "BUCKET_COUNT", value = tostring(var.bucket_count) },
        { name = "BUCKET_START", value = tostring(var.bucket_start) },
        { name = "BUCKET_END",   value = tostring(var.bucket_end) },
        { name = "DDB_GSI_NAME", value = "gsi_due_checks" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.lg.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "worker"
        }
      }
    }
  ])
}
