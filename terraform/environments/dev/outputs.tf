output "api_base_url" {
  description = "Base URL for the Jury App API (dev)"
  value       = module.stack.api_base_url
}

output "jury_api_key" {
  description = "API key for the Jury App REST API (dev)"
  value       = module.stack.jury_api_key
  sensitive   = true
}

