Bootstrap: Remote Terraform State

This tiny stack creates the shared S3 bucket and DynamoDB lock table for Terraform remote state.

What it creates
- S3 bucket: versioned, SSE-S3 encrypted, public access blocked
- Bucket policy: denies unencrypted uploads (defense-in-depth)
- DynamoDB table: PAY_PER_REQUEST, point-in-time recovery enabled

Names
- Bucket: jury-gen-tfstate-<account>-<region>
- Table:  jury-gen-terraform-locks-<account>-<region>

Usage
1) Initialize and apply (once per account/region):
   - cd bootstrap/remote-state
   - terraform init
   - terraform apply

2) Wire your main Terraform to use this backend (example CLI flags):
   - terraform init \
       -backend-config="bucket=jury-gen-tfstate-<account>-<region>" \
       -backend-config="key=terraform.tfstate" \
       -backend-config="region=<region>" \
       -backend-config="dynamodb_table=jury-gen-terraform-locks-<account>-<region>" \
       -backend-config="encrypt=true" \
       -migrate-state

You can customize the key if you later split environments.

