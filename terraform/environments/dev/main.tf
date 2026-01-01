module "stack" {
  source = "../.."

  environment               = "dev"
  ci_branch                 = "develop"
  web_branch                = "develop"
  textract_get_results_tag  = var.textract_get_results_tag
  api_export_docx_tag       = var.api_export_docx_tag
}
