terraform {
  backend "s3" {
    bucket         = "jury-gen-048401463158-96729e"
    key            = "env/prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "jury-gen-tf-locks"
    encrypt        = true
  }
}

