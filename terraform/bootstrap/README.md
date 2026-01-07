Bootstrap Terraform State (AWS)
================================

This stack creates the AWS resources Terraform uses for remote state:

- S3 bucket (versioned, encrypted, no public access)
- DynamoDB table for state locking (always created)

Usage
-----

1) Initialize and apply locally (no backend yet):

   - `cd terraform/bootstrap`
   - `terraform init`
   - `terraform apply -auto-approve`

   Optional flags:
   - `-var region=us-east-1` (default)
   - `-var kms_master_key_id=<KMS Key ARN or ID>`

2) Configure other Terraform stacks to use the backend:

   Create a `backend.hcl` file (see `../backend.hcl.example`) and reference it during init:

   - `terraform init -backend-config=../backend.hcl.example`

   Example `terraform { backend "s3" { ... } }` block for downstream stacks:

   - Place in the stack’s `terraform { backend "s3" {} }` section with no interpolations. Backend values cannot use variables.

Notes
-----

- DynamoDB locking is always created here. Keep it unless you’re using Terraform Cloud/Enterprise or another backend that provides locking. Without locking, concurrent applies can corrupt state.
- The bucket is versioned and enforces TLS to protect state. Public access is fully blocked.
- If you enable `force_destroy`, deleting the bucket will also delete all state object versions. Use with caution.
- The bucket name is automatically created as `jury-gen-<account-id>-<rand6>` to ensure uniqueness while staying recognizable. If you want a different name, change `aws_s3_bucket.tf_state.bucket` in `main.tf`.
- Sharing one bucket across environments is fine; separate environments by using distinct `key` paths in backend config (e.g., `dev/app.tfstate`, `staging/app.tfstate`, `prod/app.tfstate`). A single DynamoDB table works across all of them.
