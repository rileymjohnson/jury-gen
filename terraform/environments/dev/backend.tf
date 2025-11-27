terraform {
  backend "s3" {
    bucket         = "jury-gen-tfstate-196861676652-us-east-1"
    key            = "env/dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "jury-gen-terraform-locks-196861676652-us-east-1"
    encrypt        = true
  }
}

