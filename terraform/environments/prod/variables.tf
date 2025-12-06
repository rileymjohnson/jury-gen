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
