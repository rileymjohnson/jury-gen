# This data source gets the "identity" of your
# current AWS session (the user/role you are)
data "aws_caller_identity" "current" {}

# This data source gets the region the provider is
# currently configured to use (from the environment)
data "aws_region" "current" {}