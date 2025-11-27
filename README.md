# jury-gen

Environments
- Terraform now supports two environments: `dev` and `prod`.
- Each environment has its own root at `terraform/environments/dev` and `terraform/environments/prod`.
- All AWS resource names include an environment suffix to avoid collisions.

CI/CD
- CodePipeline is provisioned per environment and tracks branches:
  - `develop` → `dev` pipeline (`jury-gen-pipeline-dev`)
  - `main` → `prod` pipeline (`jury-gen-pipeline-prod`)
- Docker, Terraform plan, and apply steps receive `TF_ENV` to target the right env.

State
- Remote state is stored in S3 with separate keys per env:
  - `env/dev/terraform.tfstate`
  - `env/prod/terraform.tfstate`
- Locks use the existing DynamoDB table.

Local usage
- Dev: `terraform -chdir=terraform/environments/dev init && terraform -chdir=terraform/environments/dev apply`
- Prod: `terraform -chdir=terraform/environments/prod init && terraform -chdir=terraform/environments/prod apply`

Notes
- The legacy single-environment root at `terraform/` is now used as a module by the per-env roots.
- ECR repos are now per env: `jury-app/textract-get-results-dev` and `jury-app/textract-get-results-prod`.
