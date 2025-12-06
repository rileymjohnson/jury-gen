module "stack" {
  source = "../.."

  environment               = "prod"
  ci_branch                 = "main"
  web_branch                = "main"
  textract_get_results_tag  = var.textract_get_results_tag
  api_export_docx_tag       = var.api_export_docx_tag
}
