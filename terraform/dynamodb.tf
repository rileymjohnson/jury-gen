resource "aws_dynamodb_table" "jury_instructions" {
  name         = "JuryInstructions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "jury_instruction_id"

  attribute {
    name = "jury_instruction_id"
    type = "S"
  }
}

# Standard reference data: Claims
resource "aws_dynamodb_table" "claims" {
  name         = "Claims"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }
}

# Standard reference data: Standard Jury Instructions
resource "aws_dynamodb_table" "standard_jury_instructions" {
  name         = "StandardJuryInstructions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }
}

# Option B: Pure Terraform seeding using aws_dynamodb_table_item
# Reads JSON files at plan/apply time and creates one resource per item.
locals {
  claims_raw = jsondecode(file("${path.module}/data/claims.json"))
  sji_raw    = jsondecode(file("${path.module}/data/standard_jury_instructions.json"))

  claims_map = { for o in local.claims_raw : o.id => o }
  sji_map    = { for o in local.sji_raw    : o.id => o }
}

resource "aws_dynamodb_table_item" "claims_items" {
  for_each   = local.claims_map
  table_name = aws_dynamodb_table.claims.name
  hash_key   = "id"

  # Store all attributes as strings for simplicity
  item = jsonencode({ for k, v in each.value : k => { S = tostring(v) } })
}

resource "aws_dynamodb_table_item" "sji_items" {
  for_each   = local.sji_map
  table_name = aws_dynamodb_table.standard_jury_instructions.name
  hash_key   = "id"

  # Store all attributes as strings for simplicity
  item = jsonencode({ for k, v in each.value : k => { S = tostring(v) } })
}
