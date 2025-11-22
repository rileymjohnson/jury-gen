resource "aws_dynamodb_table" "jury_instructions" {
  name         = "JuryInstructions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "jury_instruction_id"

  attribute {
    name = "jury_instruction_id"
    type = "S"
  }
}