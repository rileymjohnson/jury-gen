terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  # No region = var.region
  # The provider will now automatically "deduce" the region
  # from your environment, just like the AWS CLI does
  # (e.g., from the AWS_REGION env var or ~/.aws/config).
}