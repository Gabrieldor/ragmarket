# ── EC2 instance role: allows the instance to stop itself ──

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "market_intel_instance" {
  name               = "market-intel-instance"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
  tags               = { Name = "market-intel-instance" }
}

data "aws_iam_policy_document" "instance_self_stop" {
  statement {
    actions   = ["ec2:StopInstances"]
    resources = [aws_instance.market_intel.arn]
  }
}

resource "aws_iam_policy" "instance_self_stop" {
  name   = "market-intel-self-stop"
  policy = data.aws_iam_policy_document.instance_self_stop.json
}

resource "aws_iam_role_policy_attachment" "instance_self_stop" {
  role       = aws_iam_role.market_intel_instance.name
  policy_arn = aws_iam_policy.instance_self_stop.arn
}

resource "aws_iam_instance_profile" "market_intel" {
  name = "market-intel"
  role = aws_iam_role.market_intel_instance.name
}

# ── Lambda: restarts the instance when it stops ──

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "start_instance_lambda" {
  name               = "market-intel-start-instance"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "start_instance" {
  statement {
    actions   = ["ec2:StartInstances"]
    resources = [aws_instance.market_intel.arn]
  }
  statement {
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:*:*:*"]
  }
}

resource "aws_iam_policy" "start_instance" {
  name   = "market-intel-start-instance"
  policy = data.aws_iam_policy_document.start_instance.json
}

resource "aws_iam_role_policy_attachment" "start_instance" {
  role       = aws_iam_role.start_instance_lambda.name
  policy_arn = aws_iam_policy.start_instance.arn
}

data "archive_file" "start_instance_lambda" {
  type        = "zip"
  output_path = "${path.module}/start_instance_lambda.zip"

  source {
    filename = "lambda_function.py"
    content  = <<-PYTHON
import boto3, os

def handler(event, context):
    instance_id = os.environ["INSTANCE_ID"]
    region      = os.environ["INSTANCE_REGION"]
    boto3.client("ec2", region_name=region).start_instances(InstanceIds=[instance_id])
    return {"started": instance_id}
PYTHON
  }
}

resource "aws_lambda_function" "start_instance" {
  function_name    = "market-intel-start-instance"
  role             = aws_iam_role.start_instance_lambda.arn
  handler          = "lambda_function.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.start_instance_lambda.output_path
  source_code_hash = data.archive_file.start_instance_lambda.output_base64sha256
  timeout          = 30

  environment {
    variables = {
      INSTANCE_ID     = aws_instance.market_intel.id
      INSTANCE_REGION = var.region
    }
  }

  tags = { Name = "market-intel-start-instance" }
}

# ── EventBridge: instance stopped → invoke Lambda ──

resource "aws_cloudwatch_event_rule" "instance_stopped" {
  name = "market-intel-instance-stopped"
  event_pattern = jsonencode({
    source      = ["aws.ec2"]
    detail-type = ["EC2 Instance State-change Notification"]
    detail = {
      state       = ["stopped"]
      instance-id = [aws_instance.market_intel.id]
    }
  })
}

resource "aws_cloudwatch_event_target" "start_instance" {
  rule = aws_cloudwatch_event_rule.instance_stopped.name
  arn  = aws_lambda_function.start_instance.arn
}

resource "aws_lambda_permission" "eventbridge_start_instance" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.start_instance.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.instance_stopped.arn
}
