locals {
  web_site_bucket_name = "jury-app-web-${data.aws_caller_identity.current.account_id}-${data.aws_region.current.name}${local.env_suffix}"
}

# S3 bucket for static site (private, accessed via CloudFront OAC)
resource "aws_s3_bucket" "web_site" {
  bucket = local.web_site_bucket_name
}

resource "aws_s3_bucket_public_access_block" "web_site" {
  bucket                  = aws_s3_bucket.web_site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "web_site" {
  bucket = aws_s3_bucket.web_site.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

# CloudFront OAC for S3 origin
resource "aws_cloudfront_origin_access_control" "web_oac" {
  name                              = "${aws_s3_bucket.web_site.bucket}-oac"
  description                       = "OAC for ${aws_s3_bucket.web_site.bucket}"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "web_cdn" {
  enabled             = true
  price_class         = "PriceClass_100"
  default_root_object = "index.html"

  origin {
    domain_name              = aws_s3_bucket.web_site.bucket_regional_domain_name
    origin_id                = "web-s3-origin"
    origin_access_control_id = aws_cloudfront_origin_access_control.web_oac.id
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "web-s3-origin"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }
  }

  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions { geo_restriction { restriction_type = "none" } }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# Policy allowing CloudFront to read from the bucket via OAC
resource "aws_s3_bucket_policy" "web_site" {
  bucket = aws_s3_bucket.web_site.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Sid      = "AllowCloudFrontOACRead",
      Effect   = "Allow",
      Principal = { Service = "cloudfront.amazonaws.com" },
      Action   = ["s3:GetObject"],
      Resource = ["${aws_s3_bucket.web_site.arn}/*"],
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.web_cdn.arn
        }
      }
    }]
  })
}

# CodeBuild for web build + deploy
resource "aws_iam_role" "cb_web" {
  name               = "JuryGen-CodeBuild-Web${local.env_suffix}"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "codebuild.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}

resource "aws_iam_role_policy" "cb_web" {
  name   = "cb-web-deploy-policy${local.env_suffix}"
  role   = aws_iam_role.cb_web.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = "*" },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = [aws_s3_bucket.web_site.arn] },
      { Effect = "Allow", Action = ["s3:PutObject", "s3:DeleteObject", "s3:GetObject", "s3:GetObjectVersion"], Resource = ["${aws_s3_bucket.web_site.arn}/*"] },
      { Effect = "Allow", Action = ["cloudfront:CreateInvalidation"], Resource = [aws_cloudfront_distribution.web_cdn.arn] }
    ]
  })
}

resource "aws_codebuild_project" "web_build_deploy" {
  name         = "jury-gen-web-deploy-${var.environment}"
  service_role = aws_iam_role.cb_web.arn

  artifacts { type = "CODEPIPELINE" }

  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = "aws/codebuild/standard:7.0"
    type         = "LINUX_CONTAINER"
    environment_variable { name = "WEB_S3_BUCKET" value = aws_s3_bucket.web_site.bucket }
    environment_variable { name = "WEB_CF_DISTRIBUTION_ID" value = aws_cloudfront_distribution.web_cdn.id }
    environment_variable { name = "WEB_BUILD_DIR" value = "dist" }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = "terraform/buildspec/web-deploy.yml"
  }
}


# Reuse the existing CodeStar connection for a new pipeline that sources the web repo
resource "aws_codepipeline" "web_pipeline" {
  name     = "jury-gen-web-pipeline-${var.environment}"
  role_arn = aws_iam_role.codepipeline.arn

  artifact_store {
    location = aws_s3_bucket.ci_artifacts.bucket
    type     = "S3"
  }

  stage {
    name = "Source"
    action {
      name             = "Source"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      output_artifacts = ["SourceArtifact"]
      configuration = {
        ConnectionArn    = aws_codestarconnections_connection.github.arn
        FullRepositoryId  = var.web_repository_id
        BranchName        = var.web_branch
        DetectChanges     = "true"
      }
    }
  }

  stage {
    name = "BuildAndDeploy"
    action {
      name            = "WebBuildDeploy"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["SourceArtifact"]
      configuration = {
        ProjectName = aws_codebuild_project.web_build_deploy.name
      }
    }
  }
}

output "web_bucket_name" {
  value       = aws_s3_bucket.web_site.bucket
  description = "S3 bucket name for the web site"
}

output "web_cloudfront_domain" {
  value       = aws_cloudfront_distribution.web_cdn.domain_name
  description = "CloudFront domain for the web site"
}

output "web_cloudfront_distribution_id" {
  value       = aws_cloudfront_distribution.web_cdn.id
  description = "CloudFront distribution ID for invalidations"
}

output "web_url" {
  value       = "https://${aws_cloudfront_distribution.web_cdn.domain_name}"
  description = "Public URL for the web site via CloudFront"
}
