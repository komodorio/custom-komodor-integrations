data "aws_secretsmanager_secret" "komodor_api_key" {
  name = var.komodor_api_key_secret_id
}

data "aws_secretsmanager_secret" "slack_webhook_uri" {
  count = var.slack_delivery_mode == "webhook" ? 1 : 0

  name = var.slack_webhook_uri_secret_id
}

data "aws_secretsmanager_secret" "slack_bot_token" {
  count = var.slack_delivery_mode == "bot" ? 1 : 0

  name = var.slack_bot_token_secret_id
}

data "aws_secretsmanager_secret" "webhook_token" {
  count = var.generate_webhook_token ? 0 : 1

  name = var.webhook_token_secret_id
}

ephemeral "random_password" "webhook_token" {
  count = var.generate_webhook_token ? 1 : 0

  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "webhook_token" {
  count = var.generate_webhook_token ? 1 : 0

  name = var.webhook_token_secret_id
}

resource "aws_secretsmanager_secret_version" "webhook_token" {
  count = var.generate_webhook_token ? 1 : 0

  secret_id                = aws_secretsmanager_secret.webhook_token[0].id
  secret_string_wo         = ephemeral.random_password.webhook_token[0].result
  secret_string_wo_version = var.webhook_token_generation
}

locals {
  webhook_token_secret_arn = var.generate_webhook_token ? aws_secretsmanager_secret.webhook_token[0].arn : data.aws_secretsmanager_secret.webhook_token[0].arn
  slack_secret_arn         = var.slack_delivery_mode == "bot" ? data.aws_secretsmanager_secret.slack_bot_token[0].arn : data.aws_secretsmanager_secret.slack_webhook_uri[0].arn
  slack_environment = var.slack_delivery_mode == "bot" ? {
    SLACK_BOT_TOKEN_SECRET_ARN = data.aws_secretsmanager_secret.slack_bot_token[0].arn
    SLACK_CHANNEL_ID           = var.slack_channel_id
    } : {
    SLACK_WEBHOOK_URI_SECRET_ARN = data.aws_secretsmanager_secret.slack_webhook_uri[0].arn
  }
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${var.function_name}-execution"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy_attachment" "basic_execution" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "read_secrets" {
  statement {
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      data.aws_secretsmanager_secret.komodor_api_key.arn,
      local.slack_secret_arn,
      local.webhook_token_secret_arn,
    ]
  }
}

resource "aws_iam_role_policy" "read_secrets" {
  name   = "read-rca-secrets"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.read_secrets.json
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "service" {
  function_name = var.function_name
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = var.container_image_uri

  architectures                  = ["arm64"]
  memory_size                    = var.memory_size
  timeout                        = 900
  reserved_concurrent_executions = var.reserved_concurrent_executions

  environment {
    variables = merge({
      KOMODOR_API_KEY_SECRET_ARN = data.aws_secretsmanager_secret.komodor_api_key.arn
      WEBHOOK_TOKEN_SECRET_ARN   = local.webhook_token_secret_arn
      DEFAULT_WORKLOAD_KIND      = var.default_workload_kind
      PROCESS_STATUSES           = var.process_statuses
      PROCESS_SEVERITIES         = var.process_severities
      PUBLISH_CUSTOM_EVENT       = tostring(var.publish_custom_event)
      INVESTIGATION_TIMEOUT      = var.investigation_timeout
      LOG_LEVEL                  = var.log_level
      SYNCHRONOUS_PROCESSING     = "true"
    }, local.slack_environment)
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy_attachment.basic_execution,
    aws_iam_role_policy.read_secrets,
    aws_secretsmanager_secret_version.webhook_token,
  ]
}

resource "aws_lambda_function_url" "service" {
  function_name = aws_lambda_function.service.function_name
  # Requests are authenticated by WEBHOOK_TOKEN inside the application.
  authorization_type = "NONE"

  cors {
    allow_methods = ["POST"]
    allow_origins = ["*"]
    max_age       = 300
  }
}

resource "aws_lambda_permission" "public_function_url" {
  # Required AWS resource-policy plumbing for a public NONE-auth Function URL.
  # This does not authenticate requests.
  statement_id           = "AllowPublicFunctionURL"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.service.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "public_function_invocation" {
  # New Function URLs require both public permissions. Restrict this permission
  # so it can only be exercised through the Function URL.
  statement_id             = "AllowPublicFunctionInvocationThroughFunctionURL"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.service.function_name
  principal                = "*"
  invoked_via_function_url = true
}
