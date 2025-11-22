resource "aws_ecr_repository" "textract_get_results" {
  name = "jury-app/textract-get-results" # Name for your container image
  
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "extract_legal_claims" {
  name = "jury-app/extract-legal-claims" # Name for your container image
  
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "generate_instructions" {
  name = "jury-app/generate-instructions" # Name for your container image
  
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}
