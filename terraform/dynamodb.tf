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

  # Only include items with a non-empty id
  claims_map = { for o in local.claims_raw : o.id => o if try(length(trimspace(tostring(o.id))) > 0, false) }
  sji_map    = { for o in local.sji_raw    : o.id => o if try(length(trimspace(tostring(o.id))) > 0, false) }
}

resource "aws_dynamodb_table_item" "claims_items" {
  for_each   = local.claims_map
  table_name = aws_dynamodb_table.claims.name
  hash_key   = "id"

  # Build a full attribute map, preserving scalars as types and
  # encoding complex types (lists/maps) as JSON strings.
  item = jsonencode(merge(
    { id = { S = tostring(each.value.id) } },
    { for k, v in each.value :
        k => (
          can(tomap(v))  ? { S = jsonencode(v) } :
          can(tolist(v)) ? { S = jsonencode(v) } :
          try(v == true || v == false, false) ? { BOOL = v } :
          can(tonumber(v)) ? { N = tostring(v) } :
          { S = tostring(v) }
        )
        if k != "id" && try(v != null && (can(tomap(v)) || can(tolist(v)) || length(tostring(v)) > 0), false)
    }
  ))
}

resource "aws_dynamodb_table_item" "sji_items" {
  for_each   = local.sji_map
  table_name = aws_dynamodb_table.standard_jury_instructions.name
  hash_key   = "id"

  # Build a full attribute map, preserving scalars as types and
  # encoding complex types (lists/maps) as JSON strings.
  item = jsonencode(merge(
    { id = { S = tostring(each.value.id) } },
    { for k, v in each.value :
        k => (
          can(tomap(v))  ? { S = jsonencode(v) } :
          can(tolist(v)) ? { S = jsonencode(v) } :
          try(v == true || v == false, false) ? { BOOL = v } :
          can(tonumber(v)) ? { N = tostring(v) } :
          { S = tostring(v) }
        )
        if k != "id" && try(v != null && (can(tomap(v)) || can(tolist(v)) || length(tostring(v)) > 0), false)
    }
  ))
}
