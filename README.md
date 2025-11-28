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

Local Runner
- Configure env vars with your outputs:
  - Dev: set `JURY_DEV_API_URL` and `JURY_DEV_API_KEY`
  - Prod: set `JURY_PROD_API_URL` and `JURY_PROD_API_KEY`
- Run an example end-to-end via the live API:
  - `python scripts/run_api_example.py one --env dev --api-url https://z8rj47cgo7.execute-api.us-east-1.amazonaws.com/dev --api-key <key>`
  - Flags `--api-url` and `--api-key` are optional; they default to the provided dev values.
  - Results are written to `runs/dev-one-<timestamp>/`

**Step Function Flow**
- Definition: see `terraform/step_functions.tf:1`.
- High-level flow:
  - StartJob (`lambdas/job_start`): initializes `job_data` (ID, file pointers).
  - ProcessDocuments (Parallel): three branches run Textract on inputs in parallel.
    - Complaint branch: Start → Wait 30s → Check → Choice(SUCCEEDED→GetResults | FAILED→Fail).
    - Answer branch: Start → Wait 30s → Check → Choice(SUCCEEDED→GetResults | FAILED→Fail).
    - Witness branch: Start → Wait 30s → Check → Choice(SUCCEEDED→GetResults | FAILED→Fail).
  - AssembleData (Pass): collects `complaint_chunks`, `answer_chunks`, `witness_chunks` and `job_data`.
  - ExtractCoreData (Parallel):
    - ExtractClaims: `extract_legal_claims` on complaint chunks with `claim_type="claims"`.
    - ExtractCounterclaims: `extract_legal_claims` on answer chunks with `claim_type="counterclaims"`.
    - ExtractWitnesses: `extract_witnesses` on witness chunks.
    - ExtractCaseFacts: `extract_case_facts` on complaint, answer, witness chunks.
  - AssembleCoreResults (Pass): collates claims, counterclaims, witnesses, case_facts.
  - EnrichCore (Parallel with Map):
    - EnrichClaims: map over claims via `enrich_legal_item` (adds damages/defenses).
    - EnrichCounterclaims: map over counterclaims via `enrich_legal_item` (adds damages only).
  - AssembleEnrichedResults (Pass): merges enriched outputs + chunks.
  - GenerateInstructions: `generate_instructions` produces final instructions list.
  - SaveResults: `job_save_results` persists outputs.
  - JobFailed: `job_handle_error` persists failure context.

**Lambda Overview**
- Job/Control
  - `lambdas/job_start/main.py`: seeds `job_data` and may write initial state to DynamoDB (`JuryInstructions-*`).
  - `lambdas/job_save_results/main.py`: writes final instructions and metadata to DynamoDB.
  - `lambdas/job_handle_error/main.py`: records failures and error context.

- Textract
  - `lambdas/textract_start/main.py`: kicks off Textract for an input file; stages to processing bucket.
  - `lambdas/textract_check_status/main.py`: polls Textract job status.
  - `lambdas/textract_get_results/main.py`: Docker Lambda that pages Textract results and creates text chunks.

- Core Extraction (Bedrock)
  - `lambdas/extract_legal_claims/main.py`:
    - Input: `{ "chunks": [...], "claim_type": "claims"|"counterclaims" }`.
    - Pipeline: extract raw → deduplicate → match to DynamoDB `Claims-*` table.
    - Output: `[ { "claim_id": str|null, "raw_texts": [..] }, ... ]`.
  - `lambdas/extract_witnesses/main.py`:
    - Input: `[ "chunk", ... ]` witness list text.
    - Output: `[ { "first_name": str, "last_name": str }, ... ]`.
  - `lambdas/extract_case_facts/main.py`:
    - Input: `{ complaint_chunks: [...], answer_chunks: [...], witness_chunks?: [...] }`.
    - Output: consolidated case facts string.

- Enrichment
  - `lambdas/enrich_legal_item/main.py`:
    - Map over each claim/counterclaim.
    - For claims: adds damages (from complaint) and defenses (from answer).
    - For counterclaims: adds damages (from answer).

- Synthesis
  - `lambdas/generate_instructions/main.py`:
    - Input: `{ claims: [...], counterclaims: [...], case_facts: "..." }`.
    - Joins with `StandardJuryInstructions-*` to emit tailored instruction objects.

- API (HTTP)
  - `lambdas/api_signer/main.py`: generates pre-signed S3 upload URLs for documents.
  - `lambdas/api_start/main.py`: starts an execution of the Step Function.
  - `lambdas/api_status/main.py`: reports job status and returns stored results.

See Lambda definitions and environment variables in `terraform/lambda.tf:1`.

**Local Development Aids**
- Inspect Step Functions history to get per-state Lambda inputs:
  - `scripts/extract_lambda_inputs.py` → writes JSON payloads under `examples/<one|two>/inputs`.
- Run Lambdas locally with captured inputs:
  - CLI: `scripts/run_lambda_local.py` (sets region + dev DynamoDB env vars automatically).
  - UI: `scripts/ui_app.py` (Streamlit) to browse inputs, run, and view live logs.

More details and a diagram are available in `docs/WORKFLOW.md`.
