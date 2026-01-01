output "api_base_url" {
  description = "Base URL for the Jury App API (dev)"
  value       = module.stack.api_base_url
}

output "jury_api_key" {
  description = "API key for the Jury App REST API (dev)"
  value       = module.stack.jury_api_key
  sensitive   = true
}

output "web_bucket_name" {
  description = "S3 bucket for the web app (dev)"
  value       = module.stack.web_bucket_name
}

output "web_cloudfront_domain" {
  description = "CloudFront domain for the web app (dev)"
  value       = module.stack.web_cloudfront_domain
}

output "web_cloudfront_distribution_id" {
  description = "CloudFront distribution ID for the web app (dev)"
  value       = module.stack.web_cloudfront_distribution_id
}

output "web_url" {
  description = "Public URL for the web app (dev)"
  value       = module.stack.web_url
}
