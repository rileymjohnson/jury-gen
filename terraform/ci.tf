locals {
  ci_bucket_name = "jury-gen-codepipeline-${data.aws_caller_identity.current.account_id}-${data.aws_region.current.name}"
}

resource "aws_s3_bucket" "ci_artifacts" {
  bucket = local.ci_bucket_name
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ci_artifacts" {
  bucket = aws_s3_bucket.ci_artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "ci_artifacts" {
  bucket = aws_s3_bucket.ci_artifacts.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_public_access_block" "ci_artifacts" {
  bucket                  = aws_s3_bucket.ci_artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# CodeBuild IAM Roles
resource "aws_iam_role" "cb_docker" {
  name               = "JuryGen-CodeBuild-Docker"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "codebuild.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}

resource "aws_iam_role_policy" "cb_docker" {
  name   = "cb-docker-policy"
  role   = aws_iam_role.cb_docker.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = "*" },
      { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:CompleteLayerUpload", "ecr:InitiateLayerUpload", "ecr:PutImage", "ecr:UploadLayerPart", "ecr:BatchGetImage"], Resource = "*" },
      { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion"], Resource = ["${aws_s3_bucket.ci_artifacts.arn}/*"] },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = [aws_s3_bucket.ci_artifacts.arn] }
    ]
  })
}

resource "aws_codebuild_project" "docker" {
  name         = "jury-gen-docker"
  service_role = aws_iam_role.cb_docker.arn
  artifacts {
    type = "CODEPIPELINE"
  }
  environment {
    compute_type    = "BUILD_GENERAL1_MEDIUM"
    image           = "aws/codebuild/standard:7.0"
    type            = "LINUX_CONTAINER"
    privileged_mode = true
    environment_variable {
      name  = "ACCOUNT_ID"
      value = data.aws_caller_identity.current.account_id
    }
  }
  source {
    type      = "CODEPIPELINE"
    buildspec = "terraform/buildspec/docker.yml"
  }
  cache {
    type  = "LOCAL"
    modes = ["LOCAL_DOCKER_LAYER_CACHE", "LOCAL_SOURCE_CACHE"]
  }
}

resource "aws_iam_role" "cb_tf" {
  name               = "JuryGen-CodeBuild-Terraform"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "codebuild.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}

resource "aws_iam_role_policy" "cb_tf" {
  name   = "cb-terraform-policy"
  role   = aws_iam_role.cb_tf.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = "*" },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = ["arn:aws:s3:::${var.state_bucket_name}"] },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:GetObjectVersion"], Resource = ["arn:aws:s3:::${var.state_bucket_name}/*", aws_s3_bucket.ci_artifacts.arn, "${aws_s3_bucket.ci_artifacts.arn}/*"] },
      { Effect = "Allow", Action = ["dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:GetItem", "dynamodb:UpdateItem"], Resource = "arn:aws:dynamodb:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/${var.lock_table_name}" },
      { Effect = "Allow", Action = "*", Resource = "*" }
    ]
  })
}

resource "aws_codebuild_project" "tf_plan" {
  name         = "jury-gen-tf-plan"
  service_role = aws_iam_role.cb_tf.arn
  artifacts {
    type = "CODEPIPELINE"
  }
  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = "aws/codebuild/standard:7.0"
    type         = "LINUX_CONTAINER"
  }
  source {
    type      = "CODEPIPELINE"
    buildspec = "terraform/buildspec/tf-plan.yml"
  }
}

resource "aws_codebuild_project" "tf_apply" {
  name         = "jury-gen-tf-apply"
  service_role = aws_iam_role.cb_tf.arn
  artifacts {
    type = "CODEPIPELINE"
  }
  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = "aws/codebuild/standard:7.0"
    type         = "LINUX_CONTAINER"
  }
  source {
    type      = "CODEPIPELINE"
    buildspec = "terraform/buildspec/tf-apply.yml"
  }
}

# CodePipeline IAM Role
resource "aws_iam_role" "codepipeline" {
  name               = "JuryGen-CodePipeline-Role"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "codepipeline.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}

resource "aws_iam_role_policy" "codepipeline" {
  name   = "codepipeline-policy"
  role   = aws_iam_role.codepipeline.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion", "s3:GetBucketVersioning"], Resource = [aws_s3_bucket.ci_artifacts.arn, "${aws_s3_bucket.ci_artifacts.arn}/*"] },
      { Effect = "Allow", Action = ["codebuild:BatchGetBuilds", "codebuild:StartBuild"], Resource = [aws_codebuild_project.docker.arn, aws_codebuild_project.tf_plan.arn, aws_codebuild_project.tf_apply.arn] }
    ]
  })
}

# Create a CodeStar Connections connection (requires console authorization after creation)
resource "aws_codestarconnections_connection" "github" {
  name          = "jury-gen-github-connection"
  provider_type = "GitHub"
}

resource "aws_iam_role_policy" "codepipeline_codestar" {
  name   = "codepipeline-codestar-policy"
  role   = aws_iam_role.codepipeline.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      { Effect = "Allow", Action = ["codestar-connections:UseConnection"], Resource = [aws_codestarconnections_connection.github.arn] }
    ]
  })
}

resource "aws_codepipeline" "pipeline" {
  name     = "jury-gen-pipeline"
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
        FullRepositoryId  = var.ci_repository_id
        BranchName        = var.ci_branch
        DetectChanges     = "true"
      }
    }
  }

  stage {
    name = "BuildDocker"
    action {
      name            = "Docker"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["SourceArtifact"]
      output_artifacts = ["DockerArtifact"]
      configuration = {
        ProjectName = aws_codebuild_project.docker.name
        EnvironmentVariables = jsonencode([
          { name = "ACCOUNT_ID", value = data.aws_caller_identity.current.account_id, type = "PLAINTEXT" }
        ])
      }
    }
  }

  stage {
    name = "TerraformPlan"
    action {
      name            = "Plan"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["SourceArtifact", "DockerArtifact"]
      output_artifacts = ["TfPlanArtifact"]
      configuration = {
        ProjectName = aws_codebuild_project.tf_plan.name
      }
    }
  }

  stage {
    name = "TerraformApply"
    action {
      name            = "Apply"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["SourceArtifact", "TfPlanArtifact"]
      configuration = {
        ProjectName = aws_codebuild_project.tf_apply.name
      }
    }
  }
}

output "pipeline_name" {
  value       = aws_codepipeline.pipeline.name
  description = "Name of the CodePipeline pipeline"
}

output "ci_artifacts_bucket" {
  value       = aws_s3_bucket.ci_artifacts.bucket
  description = "S3 bucket for CodePipeline artifacts"
}
