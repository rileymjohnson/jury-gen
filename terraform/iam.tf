# --- 1. IAM Policy for Basic Lambda Execution ---
# All Lambdas need this to write logs to CloudWatch.
data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_policy" "lambda_basic_logging" {
  name        = "LambdaBasicLoggingPolicy"
  description = "Allows Lambda to create and write to CloudWatch logs"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect   = "Allow",
        Action   = [
            "logs:CreateLogGroup",
            "logs:CreateLogStream",
            "logs:PutLogEvents"
        ],
        Resource = "arn:aws:logs:*:*:*"
      },
    ]
  })
}

# --- 2. Roles for each Lambda ---

resource "aws_iam_role" "job_start" {
  name               = "JobStartLambdaRole"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  # Specific permissions for this Lambda
  inline_policy {
    name = "JobStartPolicy"
    policy = jsonencode({
      Version = "2012-10-17",
      Statement = [
        {
          Effect   = "Allow",
          Action   = ["dynamodb:PutItem"],
          Resource = aws_dynamodb_table.jury_instructions.arn
        }
      ]
    })
  }
}
resource "aws_iam_role_policy_attachment" "job_start_logging" {
  role       = aws_iam_role.job_start.name
  policy_arn = aws_iam_policy.lambda_basic_logging.arn
}


resource "aws_iam_role" "textract_start" {
  name               = "TextractStartLambdaRole"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  inline_policy {
    name = "TextractStartPolicy"
    policy = jsonencode({
      Version = "2012-10-17",
      Statement = [
        { # Read from the uploads bucket
          Effect   = "Allow",
          Action   = ["s3:GetObject"],
          Resource = "${aws_s3_bucket.uploads.arn}/*"
        },
        { # Write to the processing bucket
          Effect   = "Allow",
          Action   = [
            "s3:GetObject",
            "s3:PutObject",
            "s3:DeleteObject"
          ],
          Resource = "${aws_s3_bucket.processing.arn}/*"
        },
        { # Start Textract
          Effect   = "Allow",
          Action   = ["textract:StartDocumentTextDetection"],
          Resource = "*"
        }
      ]
    })
  }
}
resource "aws_iam_role_policy_attachment" "textract_start_logging" {
  role       = aws_iam_role.textract_start.name
  policy_arn = aws_iam_policy.lambda_basic_logging.arn
}


resource "aws_iam_role" "textract_check_status" {
  name               = "TextractCheckStatusLambdaRole"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  inline_policy {
    name = "TextractCheckStatusPolicy"
    policy = jsonencode({
      Version = "2012-10-17",
      Statement = [
        {
          Effect   = "Allow",
          Action   = ["textract:GetDocumentTextDetection"],
          Resource = "*"
        }
      ]
    })
  }
}
resource "aws_iam_role_policy_attachment" "textract_check_status_logging" {
  role       = aws_iam_role.textract_check_status.name
  policy_arn = aws_iam_policy.lambda_basic_logging.arn
}


resource "aws_iam_role" "textract_get_results" {
  name               = "TextractGetResultsLambdaRole"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  inline_policy {
    name = "TextractGetResultsPolicy"
    policy = jsonencode({
      Version = "2012-10-17",
      Statement = [
        { # Get the results
          Effect   = "Allow",
          Action   = ["textract:GetDocumentTextDetection"],
          Resource = "*"
        },
        { # Delete the temp file
          Effect   = "Allow",
          Action   = ["s3:DeleteObject"],
          Resource = "${aws_s3_bucket.processing.arn}/*"
        }
      ]
    })
  }
}
resource "aws_iam_role_policy_attachment" "textract_get_results_logging" {
  role       = aws_iam_role.textract_get_results.name
  policy_arn = aws_iam_policy.lambda_basic_logging.arn
}


# --- Role for all Bedrock-using Lambdas ---
# We can create ONE policy and attach it to multiple roles
resource "aws_iam_policy" "bedrock_analyzer_policy" {
  name = "BedrockAnalyzerPolicy"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      { # Call Bedrock
        Effect   = "Allow",
        Action   = ["bedrock:InvokeModel"],
        Resource = "*" # You can restrict this to specific models
      },
      { # Read from the standard claims/instructions tables
        Effect   = "Allow",
        Action   = ["dynamodb:Scan"],
        Resource = ["*"]
      }
    ]
  })
}

# Role for extract_legal_claims
resource "aws_iam_role" "extract_legal_claims" {
  name               = "ExtractLegalClaimsLambdaRole"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}
resource "aws_iam_role_policy_attachment" "extract_legal_claims_logging" {
  role       = aws_iam_role.extract_legal_claims.name
  policy_arn = aws_iam_policy.lambda_basic_logging.arn
}
resource "aws_iam_role_policy_attachment" "extract_legal_claims_bedrock" {
  role       = aws_iam_role.extract_legal_claims.name
  policy_arn = aws_iam_policy.bedrock_analyzer_policy.arn
}

# Role for extract_witnesses
resource "aws_iam_role" "extract_witnesses" {
  name               = "ExtractWitnessesLambdaRole"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}
resource "aws_iam_role_policy_attachment" "extract_witnesses_logging" {
  role       = aws_iam_role.extract_witnesses.name
  policy_arn = aws_iam_policy.lambda_basic_logging.arn
}
resource "aws_iam_role_policy_attachment" "extract_witnesses_bedrock" {
  role       = aws_iam_role.extract_witnesses.name
  policy_arn = aws_iam_policy.bedrock_analyzer_policy.arn
}

# Role for extract_case_facts
resource "aws_iam_role" "extract_case_facts" {
  name               = "ExtractCaseFactsLambdaRole"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}
resource "aws_iam_role_policy_attachment" "extract_case_facts_logging" {
  role       = aws_iam_role.extract_case_facts.name
  policy_arn = aws_iam_policy.lambda_basic_logging.arn
}
resource "aws_iam_role_policy_attachment" "extract_case_facts_bedrock" {
  role       = aws_iam_role.extract_case_facts.name
  policy_arn = aws_iam_policy.bedrock_analyzer_policy.arn
}

# Role for enrich_legal_item
resource "aws_iam_role" "enrich_legal_item" {
  name               = "EnrichLegalItemLambdaRole"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}
resource "aws_iam_role_policy_attachment" "enrich_legal_item_logging" {
  role       = aws_iam_role.enrich_legal_item.name
  policy_arn = aws_iam_policy.lambda_basic_logging.arn
}
resource "aws_iam_role_policy_attachment" "enrich_legal_item_bedrock" {
  role       = aws_iam_role.enrich_legal_item.name
  policy_arn = aws_iam_policy.bedrock_analyzer_policy.arn
}

# Role for generate_instructions
resource "aws_iam_role" "generate_instructions" {
  name               = "GenerateInstructionsLambdaRole"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}
resource "aws_iam_role_policy_attachment" "generate_instructions_logging" {
  role       = aws_iam_role.generate_instructions.name
  policy_arn = aws_iam_policy.lambda_basic_logging.arn
}
resource "aws_iam_role_policy_attachment" "generate_instructions_bedrock" {
  role       = aws_iam_role.generate_instructions.name
  policy_arn = aws_iam_policy.bedrock_analyzer_policy.arn
}


# --- Roles for Job Finish ---
resource "aws_iam_role" "job_save_results" {
  name               = "JobSaveResultsLambdaRole"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  inline_policy {
    name = "JobSaveResultsPolicy"
    policy = jsonencode({
      Version = "2012-10-17",
      Statement = [
        {
          Effect   = "Allow",
          Action   = ["dynamodb:UpdateItem"],
          Resource = aws_dynamodb_table.jury_instructions.arn
        }
      ]
    })
  }
}
resource "aws_iam_role_policy_attachment" "job_save_results_logging" {
  role       = aws_iam_role.job_save_results.name
  policy_arn = aws_iam_policy.lambda_basic_logging.arn
}

# --- API Lambdas IAM ---

 


resource "aws_iam_role" "job_handle_error" {
  name               = "JobHandleErrorLambdaRole"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  inline_policy {
    name = "JobHandleErrorPolicy"
    policy = jsonencode({
      Version = "2012-10-17",
      Statement = [
        {
          Effect   = "Allow",
          Action   = ["dynamodb:UpdateItem"],
          Resource = aws_dynamodb_table.jury_instructions.arn
        }
      ]
    })
  }
}
resource "aws_iam_role_policy_attachment" "job_handle_error_logging" {
  role       = aws_iam_role.job_handle_error.name
  policy_arn = aws_iam_policy.lambda_basic_logging.arn
}


# --- 3. IAM Role for the Step Function ---
# The Step Function needs permission to *invoke* all these Lambdas
data "aws_iam_policy_document" "sfn_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      # This is different from a Lambda role
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sfn_execution_role" {
  name               = "JuryAppStepFunctionRole"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume_role.json

  # Give it permission to invoke *all* our Lambdas
  inline_policy {
    name = "StepFunctionLambdaInvokePolicy"
    policy = jsonencode({
      Version = "2012-10-17",
      Statement = [
        {
          Effect   = "Allow",
          Action   = ["lambda:InvokeFunction"],
          Resource = [
            aws_lambda_function.job_start.arn,
            aws_lambda_function.textract_start.arn,
            aws_lambda_function.textract_check_status.arn,
            aws_lambda_function.textract_get_results.arn,
            aws_lambda_function.extract_legal_claims.arn,
            aws_lambda_function.extract_witnesses.arn,
            aws_lambda_function.extract_case_facts.arn,
            aws_lambda_function.enrich_legal_item.arn,
            aws_lambda_function.generate_instructions.arn,
            aws_lambda_function.job_save_results.arn,
            aws_lambda_function.job_handle_error.arn,
          ]
        }
      ]
    })
  }
}
