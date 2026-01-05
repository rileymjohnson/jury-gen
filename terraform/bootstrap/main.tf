terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.5"
    }
  }
}

provider "aws" {
  region = var.region
}

# --- Variables ---
variable "region" {
  description = "AWS region to create bootstrap resources in"
  type        = string
  default     = "us-east-1"
}

data "aws_caller_identity" "current" {}

resource "random_id" "suffix" {
  byte_length = 3 # 6 hex chars
}

variable "force_destroy" {
  description = "Allow bucket deletion even with objects (use carefully)"
  type        = bool
  default     = false
}

variable "kms_master_key_id" {
  description = "Optional KMS Key ID/ARN for SSE-KMS. If null, uses SSE-S3 (AES256)."
  type        = string
  default     = null
}

# --- S3 Bucket for state ---
resource "aws_s3_bucket" "tf_state" {
  bucket        = "jury-gen-${data.aws_caller_identity.current.account_id}-${random_id.suffix.hex}"
  force_destroy = var.force_destroy

  tags = {
    Project     = "jury-gen"
    Terraform   = "true"
    Purpose     = "terraform-state"
  }
}

resource "aws_s3_bucket_versioning" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_master_key_id == null ? "AES256" : "aws:kms"
      kms_master_key_id = var.kms_master_key_id
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tf_state" {
  bucket                  = aws_s3_bucket.tf_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "enforce_tls" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.tf_state.arn,
      "${aws_s3_bucket.tf_state.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "enforce_tls" {
  bucket = aws_s3_bucket.tf_state.id
  policy = data.aws_iam_policy_document.enforce_tls.json
}

# --- DynamoDB table for state locking (recommended) ---
resource "aws_dynamodb_table" "tf_lock" {
  name         = "jury-gen-tf-locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    Project     = "jury-gen"
    Terraform   = "true"
    Purpose     = "terraform-locks"
  }
}

# --- Outputs ---
output "state_bucket_name" {
  value       = aws_s3_bucket.tf_state.bucket
  description = "Name of the Terraform state bucket"
}

output "state_bucket_arn" {
  value       = aws_s3_bucket.tf_state.arn
  description = "ARN of the Terraform state bucket"
}

output "dynamodb_table_name" {
  value       = aws_dynamodb_table.tf_lock.name
  description = "Name of the DynamoDB lock table"
}
