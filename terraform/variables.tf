variable "extract_legal_claims_tag" {
  description = "ECR image tag for the extract_legal_claims Lambda image"
  type        = string
  default     = "latest"
}

variable "generate_instructions_tag" {
  description = "ECR image tag for the generate_instructions Lambda image"
  type        = string
  default     = "latest"
}

variable "textract_get_results_tag" {
  description = "ECR image tag for the textract_get_results Lambda image"
  type        = string
  default     = "latest"
}

variable "api_export_docx_tag" {
  description = "ECR image tag for the api_export_docx Lambda image"
  type        = string
  default     = "latest"
}

variable "ci_branch" {
  description = "Branch to build from"
  type        = string
  default     = "main"
}

variable "ci_repository_id" {
  description = "Repository identifier for CodeStar Connections (e.g., 'owner/repo')"
  type        = string
  default     = "rileymjohnson/jury-gen"
}

variable "web_repository_id" {
  description = "Frontend repository for CodePipeline (e.g., 'owner/repo')"
  type        = string
  default     = "rileymjohnson/jury-gen-web"
}

variable "web_branch" {
  description = "Branch of the frontend repo to build/deploy"
  type        = string
  default     = "main"
}

variable "state_bucket_name" {
  description = "S3 bucket name for Terraform remote state (for CodeBuild access)"
  type        = string
  default     = "jury-gen-tfstate-196861676652-us-east-1"
}

variable "lock_table_name" {
  description = "DynamoDB table name for Terraform state locking (for CodeBuild access)"
  type        = string
  default     = "jury-gen-terraform-locks-196861676652-us-east-1"
}

variable "environment" {
  description = "Deployment environment name (e.g., 'dev' or 'prod')"
  type        = string
}
