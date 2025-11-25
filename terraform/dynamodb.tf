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

  # Explicit schema for Claims items
  # Ensures attributes are always written with expected DynamoDB types
  item = jsonencode(merge(
    { id = { S = tostring(each.value.id) } },
    try(length(trimspace(tostring(each.value.title))) > 0, false) ? { title = { S = tostring(each.value.title) } } : {},
    # description may be null; use NULL=true when null, or S when non-empty
    try(each.value.description, null) == null ? { description = { NULL = true } } : (
      try(length(trimspace(tostring(each.value.description))) > 0, false) ? { description = { S = tostring(each.value.description) } } : {}
    ),
    # elements: list of strings (possibly empty)
    { elements = { L = [ for s in try(each.value.elements, []) : { S = tostring(s) } ] } },
    # defenses: list of strings (possibly empty)
    { defenses = { L = [ for s in try(each.value.defenses, []) : { S = tostring(s) } ] } }
  ))
}

resource "aws_dynamodb_table_item" "sji_items" {
  for_each   = local.sji_map
  table_name = aws_dynamodb_table.standard_jury_instructions.name
  hash_key   = "id"

  # Explicit schema for Standard Jury Instructions items
  item = jsonencode(merge(
    { id = { S = tostring(each.value.id) } },
    try(length(trimspace(tostring(each.value.number))) > 0, false) ? { number = { S = tostring(each.value.number) } } : {},
    try(length(trimspace(tostring(each.value.title))) > 0, false) ? { title = { S = tostring(each.value.title) } } : {},
    try(length(trimspace(tostring(each.value.category_title))) > 0, false) ? { category_title = { S = tostring(each.value.category_title) } } : {},
    try(length(trimspace(tostring(each.value.category_number))) > 0, false) ? { category_number = { S = tostring(each.value.category_number) } } : {},
    try(length(trimspace(tostring(each.value.url))) > 0, false) ? { url = { S = tostring(each.value.url) } } : {},
    # Use NULL=true when null, or S when non-empty
    try(each.value.main_paragraph, null) == null ? { main_paragraph = { NULL = true } } : (
      try(length(trimspace(tostring(each.value.main_paragraph))) > 0, false) ? { main_paragraph = { S = tostring(each.value.main_paragraph) } } : {}
    ),
    try(each.value.notes_on_use, null) == null ? { notes_on_use = { NULL = true } } : (
      try(length(trimspace(tostring(each.value.notes_on_use))) > 0, false) ? { notes_on_use = { S = tostring(each.value.notes_on_use) } } : {}
    )
  ))
}
