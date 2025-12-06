resource "aws_ecr_repository" "textract_get_results" {
  name = "jury-app/textract-get-results-${var.environment}" # Name for your container image
  
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "api_export_docx" {
  name = "jury-app/api-export-docx-${var.environment}"

  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}
