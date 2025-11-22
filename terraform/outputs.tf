output "jury_api_key" {
  description = "API key for the Jury App REST API"
  value       = random_password.jury_api_key.result
  sensitive   = true
}

output "api_base_url" {
  description = "Base URL for the Jury App API"
  value       = "https://${aws_api_gateway_rest_api.jury_api.id}.execute-api.${data.aws_region.current.name}.amazonaws.com/${aws_api_gateway_stage.prod.stage_name}"
}
