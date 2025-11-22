output "jury_api_key" {
  description = "API key for the Jury App REST API"
  value       = random_password.jury_api_key.result
  sensitive   = true
}

