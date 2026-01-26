resource "aws_dynamodb_table" "jury_instructions" {
  name         = "JuryInstructions${local.env_suffix}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "jury_instruction_id"

  attribute {
    name = "jury_instruction_id"
    type = "S"
  }
}

# Standard reference data: Claims
resource "aws_dynamodb_table" "claims" {
  name         = "Claims${local.env_suffix}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }
}

# Standard reference data: Standard Jury Instructions
resource "aws_dynamodb_table" "standard_jury_instructions" {
  name         = "StandardJuryInstructions${local.env_suffix}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }
}

# Standard reference data: Model Verdict Forms (separate table)
resource "aws_dynamodb_table" "model_verdict_forms" {
  name         = "ModelVerdictForms${local.env_suffix}"
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
  mvf_raw    = jsondecode(file("${path.module}/data/model_verdict_forms.json"))

  # Only include items with a non-empty id
  claims_map = { for o in local.claims_raw : o.id => o if try(length(trimspace(tostring(o.id))) > 0, false) }
  sji_map    = { for o in local.sji_raw    : o.id => o if try(length(trimspace(tostring(o.id))) > 0, false) }
  mvf_map    = { for o in local.mvf_raw    : o.id => o if try(length(trimspace(tostring(o.id))) > 0, false) }
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
    # description: only store when non-empty (omit when null/empty)
    try(length(trimspace(tostring(each.value.description))) > 0, false) ? { description = { S = tostring(each.value.description) } } : {},
    # elements: list of strings (possibly empty)
    { elements = { L = [ for s in try(each.value.elements, []) : { S = tostring(s) } ] } },
    # defenses: list of strings (possibly empty)
    { defenses = { L = [ for s in try(each.value.defenses, []) : { S = tostring(s) } ] } },
    # damages: nested object -> DynamoDB map (M) with typed fields
    (
      try(each.value.damages, null) != null ? {
        damages = {
          M = merge(
            # Strings (only when non-empty)
            try(length(trimspace(tostring(each.value.damages.verdict_form))) > 0, false) ? { verdict_form = { S = tostring(each.value.damages.verdict_form) } } : {},
            try(length(trimspace(tostring(each.value.damages.category_instruction))) > 0, false) ? { category_instruction = { S = tostring(each.value.damages.category_instruction) } } : {},
            try(length(trimspace(tostring(each.value.damages.burden_of_proof))) > 0, false) ? { burden_of_proof = { S = tostring(each.value.damages.burden_of_proof) } } : {},
            try(length(trimspace(tostring(each.value.damages.claim_category))) > 0, false) ? { claim_category = { S = tostring(each.value.damages.claim_category) } } : {},
            try(length(trimspace(tostring(each.value.damages.notes))) > 0, false) ? { notes = { S = tostring(each.value.damages.notes) } } : {},
            try(length(trimspace(tostring(each.value.damages.mapping_status))) > 0, false) ? { mapping_status = { S = tostring(each.value.damages.mapping_status) } } : {},
            # Lists
            { damages_instructions = { L = [ for s in try(each.value.damages.damages_instructions, []) : { S = tostring(s) } ] } },
            # Booleans (include when not null)
            try(each.value.damages.allows_punitive, null) != null ? { allows_punitive = { BOOL = tobool(each.value.damages.allows_punitive) } } : {},
            try(each.value.damages.requires_clear_and_convincing, null) != null ? { requires_clear_and_convincing = { BOOL = tobool(each.value.damages.requires_clear_and_convincing) } } : {},
            try(each.value.damages.equitable_relief, null) != null ? { equitable_relief = { BOOL = tobool(each.value.damages.equitable_relief) } } : {},
            try(each.value.damages.generate_from_elements, null) != null ? { generate_from_elements = { BOOL = tobool(each.value.damages.generate_from_elements) } } : {}
          )
        }
      } : {}
    )
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
    # Only store text when non-empty (omit when null/empty)
    try(length(trimspace(tostring(each.value.main_paragraph))) > 0, false) ? { main_paragraph = { S = tostring(each.value.main_paragraph) } } : {},
    try(length(trimspace(tostring(each.value.notes_on_use))) > 0, false) ? { notes_on_use = { S = tostring(each.value.notes_on_use) } } : {}
  ))
}

# Seed Model Verdict Forms items from JSON
resource "aws_dynamodb_table_item" "model_verdict_forms_items" {
  for_each   = local.mvf_map
  table_name = aws_dynamodb_table.model_verdict_forms.name
  hash_key   = "id"

  # Explicit schema for Model Verdict Forms items — mirrors SJI fields
  item = jsonencode(merge(
    { id = { S = tostring(each.value.id) } },
    try(length(trimspace(tostring(each.value.number))) > 0, false) ? { number = { S = tostring(each.value.number) } } : {},
    try(length(trimspace(tostring(each.value.title))) > 0, false) ? { title = { S = tostring(each.value.title) } } : {},
    try(length(trimspace(tostring(each.value.category_title))) > 0, false) ? { category_title = { S = tostring(each.value.category_title) } } : {},
    try(length(trimspace(tostring(each.value.category_number))) > 0, false) ? { category_number = { S = tostring(each.value.category_number) } } : {},
    try(length(trimspace(tostring(each.value.url))) > 0, false) ? { url = { S = tostring(each.value.url) } } : {},
    try(length(trimspace(tostring(each.value.main_paragraph))) > 0, false) ? { main_paragraph = { S = tostring(each.value.main_paragraph) } } : {},
    try(length(trimspace(tostring(each.value.notes_on_use))) > 0, false) ? { notes_on_use = { S = tostring(each.value.notes_on_use) } } : {}
  ))
}
