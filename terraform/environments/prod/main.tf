module "stack" {
  source = "../.."

  environment               = "prod"
  ci_branch                 = "main"
  textract_get_results_tag  = var.textract_get_results_tag
}

