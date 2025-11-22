# --- Data source to zip our Lambda folders ---
# We'll create one for each non-Docker Lambda

data "archive_file" "job_start" {
  type        = "zip"
  source_dir  = abspath("${path.module}/../lambdas/job_start/")
  output_path = abspath("${path.module}/.build/job_start.zip")
}
# ... (repeat this for all 10 non-Docker Lambdas) ...
data "archive_file" "job_save_results" {
  type        = "zip"
  source_dir  = abspath("${path.module}/../lambdas/job_save_results/")
  output_path = abspath("${path.module}/.build/job_save_results.zip")
}
data "archive_file" "job_handle_error" {
  type        = "zip"
  source_dir  = abspath("${path.module}/../lambdas/job_handle_error/")
  output_path = abspath("${path.module}/.build/job_handle_error.zip")
}
data "archive_file" "textract_start" {
  type        = "zip"
  source_dir  = abspath("${path.module}/../lambdas/textract_start/")
  output_path = abspath("${path.module}/.build/textract_start.zip")
}
data "archive_file" "textract_check_status" {
  type        = "zip"
  source_dir  = abspath("${path.module}/../lambdas/textract_check_status/")
  output_path = abspath("${path.module}/.build/textract_check_status.zip")
}
data "archive_file" "extract_legal_claims" {
  type        = "zip"
  source_dir  = abspath("${path.module}/../lambdas/extract_legal_claims/")
  output_path = abspath("${path.module}/.build/extract_legal_claims.zip")
}
data "archive_file" "extract_witnesses" {
  type        = "zip"
  source_dir  = abspath("${path.module}/../lambdas/extract_witnesses/")
  output_path = abspath("${path.module}/.build/extract_witnesses.zip")
}
data "archive_file" "extract_case_facts" {
  type        = "zip"
  source_dir  = abspath("${path.module}/../lambdas/extract_case_facts/")
  output_path = abspath("${path.module}/.build/extract_case_facts.zip")
}
data "archive_file" "enrich_legal_item" {
  type        = "zip"
  source_dir  = abspath("${path.module}/../lambdas/enrich_legal_item/")
  output_path = abspath("${path.module}/.build/enrich_legal_item.zip")
}
data "archive_file" "generate_instructions" {
  type        = "zip"
  source_dir  = abspath("${path.module}/../lambdas/generate_instructions/")
  output_path = abspath("${path.module}/.build/generate_instructions.zip")
}

# --- API Lambdas (zip)
 


# --- Lambda Function Definitions ---

resource "aws_lambda_function" "job_start" {
  function_name    = "JuryApp-JobStart"
  handler          = "main.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.job_start.arn
  filename         = data.archive_file.job_start.output_path
  source_code_hash = data.archive_file.job_start.output_base64sha256
  timeout          = 30

  environment {
    variables = {
      DYNAMODB_TABLE_NAME = aws_dynamodb_table.jury_instructions.name
    }
  }
}

resource "aws_lambda_function" "textract_start" {
  function_name    = "JuryApp-TextractStart"
  handler          = "main.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.textract_start.arn
  filename         = data.archive_file.textract_start.output_path
  source_code_hash = data.archive_file.textract_start.output_base64sha256
  timeout          = 60 # S3 copy can take time

  environment {
    variables = {
      PROCESSING_BUCKET_NAME = aws_s3_bucket.processing.id
    }
  }
}

resource "aws_lambda_function" "textract_check_status" {
  function_name    = "JuryApp-TextractCheckStatus"
  handler          = "main.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.textract_check_status.arn
  filename         = data.archive_file.textract_check_status.output_path
  source_code_hash = data.archive_file.textract_check_status.output_base64sha256
  timeout          = 15
}

# --- The Docker Lambda ---
resource "aws_lambda_function" "textract_get_results" {
  function_name = "JuryApp-TextractGetResults"
  role          = aws_iam_role.textract_get_results.arn
  package_type  = "Image"
  timeout       = 300 # Textract paging and chunking can take time

  # YOU MUST build and push your Docker image to ECR first!
  # The URI format is: <account_id>.dkr.ecr.<region>.amazonaws.com/<repo_name>:<tag>
  image_uri = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${data.aws_region.current.name}.amazonaws.com/${aws_ecr_repository.textract_get_results.name}:${var.textract_get_results_tag}"
}

# --- Bedrock Lambdas ---
resource "aws_lambda_function" "extract_legal_claims" {
  function_name = "JuryApp-ExtractLegalClaims"
  role          = aws_iam_role.extract_legal_claims.arn
  package_type  = "Image"
  timeout       = 600 # This has many Bedrock calls

  image_uri = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${data.aws_region.current.name}.amazonaws.com/${aws_ecr_repository.extract_legal_claims.name}:${var.extract_legal_claims_tag}"
}

resource "aws_lambda_function" "extract_witnesses" {
  function_name    = "JuryApp-ExtractWitnesses"
  handler          = "main.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.extract_witnesses.arn
  filename         = data.archive_file.extract_witnesses.output_path
  source_code_hash = data.archive_file.extract_witnesses.output_base64sha256
  timeout          = 300
}

resource "aws_lambda_function" "extract_case_facts" {
  function_name    = "JuryApp-ExtractCaseFacts"
  handler          = "main.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.extract_case_facts.arn
  filename         = data.archive_file.extract_case_facts.output_path
  source_code_hash = data.archive_file.extract_case_facts.output_base64sha256
  timeout          = 900 # This is your longest-running Lambda
}

resource "aws_lambda_function" "enrich_legal_item" {
  function_name    = "JuryApp-EnrichLegalItem"
  handler          = "main.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.enrich_legal_item.arn
  filename         = data.archive_file.enrich_legal_item.output_path
  source_code_hash = data.archive_file.enrich_legal_item.output_base64sha256
  timeout          = 600
}

resource "aws_lambda_function" "generate_instructions" {
  function_name = "JuryApp-GenerateInstructions"
  role          = aws_iam_role.generate_instructions.arn
  package_type  = "Image"
  timeout       = 900 # This is also very long

  # Using pre-created ECR repo for this image
  # Update the repository path below if your repo name differs
  image_uri = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${data.aws_region.current.name}.amazonaws.com/jury-app/generate-instructions:${var.generate_instructions_tag}"
}

# --- Job Finish Lambdas ---
resource "aws_lambda_function" "job_save_results" {
  function_name    = "JuryApp-JobSaveResults"
  handler          = "main.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.job_save_results.arn
  filename         = data.archive_file.job_save_results.output_path
  source_code_hash = data.archive_file.job_save_results.output_base64sha256
  timeout          = 30

  environment {
    variables = {
      DYNAMODB_TABLE_NAME = aws_dynamodb_table.jury_instructions.name
    }
  }
}

resource "aws_lambda_function" "job_handle_error" {
  function_name    = "JuryApp-JobHandleError"
  handler          = "main.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.job_handle_error.arn
  filename         = data.archive_file.job_handle_error.output_path
  source_code_hash = data.archive_file.job_handle_error.output_base64sha256
  timeout          = 30

  environment {
    variables = {
      DYNAMODB_TABLE_NAME = aws_dynamodb_table.jury_instructions.name
    }
  }
}

# --- API Lambda Functions ---
 
