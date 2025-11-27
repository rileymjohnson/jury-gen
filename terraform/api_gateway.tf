resource "aws_api_gateway_rest_api" "jury_api" {
  name        = "jury-app-api${local.env_suffix}"
  description = "API for signer, start, and status endpoints"
}

# Root resources
resource "aws_api_gateway_resource" "jury" {
  rest_api_id = aws_api_gateway_rest_api.jury_api.id
  parent_id   = aws_api_gateway_rest_api.jury_api.root_resource_id
  path_part   = "jury"
}

resource "aws_api_gateway_resource" "jury_start" {
  rest_api_id = aws_api_gateway_rest_api.jury_api.id
  parent_id   = aws_api_gateway_resource.jury.id
  path_part   = "start"
}

resource "aws_api_gateway_resource" "jury_status" {
  rest_api_id = aws_api_gateway_rest_api.jury_api.id
  parent_id   = aws_api_gateway_resource.jury.id
  path_part   = "status"
}

resource "aws_api_gateway_resource" "jury_status_id" {
  rest_api_id = aws_api_gateway_rest_api.jury_api.id
  parent_id   = aws_api_gateway_resource.jury_status.id
  path_part   = "{id}"
}

resource "aws_api_gateway_resource" "sign" {
  rest_api_id = aws_api_gateway_rest_api.jury_api.id
  parent_id   = aws_api_gateway_rest_api.jury_api.root_resource_id
  path_part   = "sign"
}

# Methods (API key required)
resource "aws_api_gateway_method" "sign_post" {
  rest_api_id     = aws_api_gateway_rest_api.jury_api.id
  resource_id     = aws_api_gateway_resource.sign.id
  http_method     = "POST"
  authorization   = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_method" "jury_start_post" {
  rest_api_id     = aws_api_gateway_rest_api.jury_api.id
  resource_id     = aws_api_gateway_resource.jury_start.id
  http_method     = "POST"
  authorization   = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_method" "jury_status_get" {
  rest_api_id     = aws_api_gateway_rest_api.jury_api.id
  resource_id     = aws_api_gateway_resource.jury_status_id.id
  http_method     = "GET"
  authorization   = "NONE"
  api_key_required = true
  request_parameters = {
    "method.request.path.id" = true
  }
}

# Integrations (Lambda proxy)
resource "aws_api_gateway_integration" "sign_post" {
  rest_api_id             = aws_api_gateway_rest_api.jury_api.id
  resource_id             = aws_api_gateway_resource.sign.id
  http_method             = aws_api_gateway_method.sign_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.api_signer.invoke_arn
}

resource "aws_api_gateway_integration" "jury_start_post" {
  rest_api_id             = aws_api_gateway_rest_api.jury_api.id
  resource_id             = aws_api_gateway_resource.jury_start.id
  http_method             = aws_api_gateway_method.jury_start_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.api_start.invoke_arn
}

resource "aws_api_gateway_integration" "jury_status_get" {
  rest_api_id             = aws_api_gateway_rest_api.jury_api.id
  resource_id             = aws_api_gateway_resource.jury_status_id.id
  http_method             = aws_api_gateway_method.jury_status_get.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.api_status.invoke_arn
  request_parameters = {
    "integration.request.path.id" = "method.request.path.id"
  }
}

# Deployment and stage
resource "aws_api_gateway_deployment" "jury_api_deployment" {
  rest_api_id = aws_api_gateway_rest_api.jury_api.id
  triggers = {
    redeploy = sha1(join(",",
      [
        aws_api_gateway_method.sign_post.id,
        aws_api_gateway_method.jury_start_post.id,
        aws_api_gateway_method.jury_status_get.id,
        aws_api_gateway_integration.sign_post.id,
        aws_api_gateway_integration.jury_start_post.id,
        aws_api_gateway_integration.jury_status_get.id
      ]
    ))
  }
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "stage" {
  rest_api_id   = aws_api_gateway_rest_api.jury_api.id
  deployment_id = aws_api_gateway_deployment.jury_api_deployment.id
  stage_name    = var.environment
}

# API Key and Usage Plan
resource "aws_api_gateway_api_key" "edge_key" {
  name      = "jury-app-edge-key${local.env_suffix}"
  enabled   = true
  value     = random_password.jury_api_key.result
}

resource "aws_api_gateway_usage_plan" "plan" {
  name = "jury-app-plan${local.env_suffix}"
  api_stages {
    api_id = aws_api_gateway_rest_api.jury_api.id
    stage  = aws_api_gateway_stage.stage.stage_name
  }
  throttle_settings {
    burst_limit = 50
    rate_limit  = 25
  }
}

resource "aws_api_gateway_usage_plan_key" "edge_key_attach" {
  key_id        = aws_api_gateway_api_key.edge_key.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.plan.id
}

# Lambda permissions for API Gateway
resource "aws_lambda_permission" "allow_apigw_sign" {
  statement_id  = "AllowAPIGatewayInvokeSign"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_signer.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.jury_api.execution_arn}/*/*/sign"
}

resource "aws_lambda_permission" "allow_apigw_start" {
  statement_id  = "AllowAPIGatewayInvokeStart"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_start.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.jury_api.execution_arn}/*/*/jury/start"
}

resource "aws_lambda_permission" "allow_apigw_status" {
  statement_id  = "AllowAPIGatewayInvokeStatus"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_status.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.jury_api.execution_arn}/*/*/jury/status/*"
}
