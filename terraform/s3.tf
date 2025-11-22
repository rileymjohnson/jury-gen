# 1. Bucket for users to upload their original documents
resource "aws_s3_bucket" "uploads" {
  bucket = "jury-app-uploads-${data.aws_caller_identity.current.account_id}"
}

# CORS for browser uploads to presigned URLs
resource "aws_s3_bucket_cors_configuration" "uploads_cors" {
  bucket = aws_s3_bucket.uploads.id

  cors_rule {
    id              = "uploads-presigned"
    allowed_methods = ["PUT", "GET", "HEAD"]
    allowed_origins = ["*"]
    allowed_headers = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

# 1a. Block public access for the uploads bucket
# This is its own resource, referencing the bucket above.
resource "aws_s3_bucket_public_access_block" "uploads_public_access" {
  bucket                  = aws_s3_bucket.uploads.id # <-- Correctly references the bucket ID
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# 2. Bucket for Textract to read from (and for our temp copies)
resource "aws_s3_bucket" "processing" {
  bucket = "jury-app-processing-${data.aws_caller_identity.current.account_id}"
}

# 2a. Block public access for the processing bucket
resource "aws_s3_bucket_public_access_block" "processing_public_access" {
  bucket                  = aws_s3_bucket.processing.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Allow Amazon Textract to read objects from the processing bucket
resource "aws_s3_bucket_policy" "processing_textract_access" {
  bucket = aws_s3_bucket.processing.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Sid      = "AllowTextractBucketAccess",
        Effect   = "Allow",
        Principal = { Service = "textract.amazonaws.com" },
        Action   = [
          "s3:GetBucketLocation",
          "s3:ListBucket"
        ],
        Resource = aws_s3_bucket.processing.arn,
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          },
          ArnLike = {
            "aws:SourceArn" = "arn:aws:textract:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
          }
        }
      },
      {
        Sid      = "AllowTextractObjectRead",
        Effect   = "Allow",
        Principal = { Service = "textract.amazonaws.com" },
        Action   = [
          "s3:GetObject",
          "s3:GetObjectVersion"
        ],
        Resource = "${aws_s3_bucket.processing.arn}/*",
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          },
          ArnLike = {
            "aws:SourceArn" = "arn:aws:textract:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
          }
        }
      }
    ]
  })
}

# Default SSE-S3 encryption on processing bucket to avoid KMS complications
resource "aws_s3_bucket_server_side_encryption_configuration" "processing_sse" {
  bucket = aws_s3_bucket.processing.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# 3. (Optional) Bucket for large results
resource "aws_s3_bucket" "results" {
  bucket = "jury-app-results-${data.aws_caller_identity.current.account_id}"
}

# 3a. Block public access for the results bucket
resource "aws_s3_bucket_public_access_block" "results_public_access" {
  bucket                  = aws_s3_bucket.results.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
