import datetime
import json
import logging
import os

import boto3

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize DynamoDB client
dynamodb = boto3.resource("dynamodb")

try:
    TABLE_NAME = os.environ["DYNAMODB_TABLE_NAME"]
    table = dynamodb.Table(TABLE_NAME)
except KeyError:
    logger.error("DYNAMODB_TABLE_NAME environment variable not set.")
    raise


def lambda_handler(event, context):
    """
    Handles any errors from the Step Function.

    1. Receives the input state, which should include 'jury_instruction_id'
       and an 'error' block from the Step Function's Catch.
    2. Parses the error.
    3. Updates the DynamoDB item's status to "ERROR".
    """

    # 1. Get Job ID
    # We assume the Step Function's Catch block is configured
    # to pass the original input, which includes 'jury_instruction_id'.
    job_id = event.get("jury_instruction_id")

    if not job_id:
        logger.error("FATAL: Could not determine jury_instruction_id from error event.")
        logger.error(f"Event: {json.dumps(event)}")
        # If we don't have a job ID, we can't update DynamoDB.
        # We must exit.
        return

    logger.info(f"Handling error for job {job_id}...")

    # 2. Parse the error
    # We expect the Step Function 'Catch' to add an 'error' field.
    error_info = event.get("error", {})
    error_type = error_info.get("Error", "UnknownError")
    error_cause_raw = error_info.get("Cause", "{}")

    error_message = f"Error: {error_type}"

    try:
        # The 'Cause' is often a JSON string. Parsing it gives
        # a much cleaner error message.
        cause_json = json.loads(error_cause_raw)
        error_message = cause_json.get("errorMessage", str(cause_json))
    except json.JSONDecodeError:
        # If it's not JSON, just use the raw string
        error_message = error_cause_raw

    logger.error(f"Parsed error message: {error_message}")

    completed_at = datetime.datetime.utcnow().isoformat()

    # 3. Update DynamoDB
    try:
        table.update_item(
            Key={"jury_instruction_id": job_id},
            UpdateExpression=("SET #status = :s, " "#completedAt = :ca, " "#error_message = :em"),
            ExpressionAttributeNames={
                "#status": "status",
                "#completedAt": "completedAt",
                "#error_message": "error_message",
            },
            ExpressionAttributeValues={":s": "ERROR", ":ca": completed_at, ":em": error_message},
        )

        logger.info(f"Successfully marked job {job_id} as ERROR in DynamoDB.")

        # This function should *not* raise an error.
        # We are successfully *handling* the error.
        # We can return the error message for logging.
        return {
            "statusCode": 200,
            "body": json.dumps(
                {"message": "Error successfully handled", "jury_instruction_id": job_id, "error": error_message}
            ),
        }

    except Exception as e:
        logger.error(f"CRITICAL: Failed to update DynamoDB for job {job_id} during error handling.")
        logger.error(str(e))
        # This is a "meta-error" (the error handler failed).
        # We must raise this so the Step Function logs it as a
        # "Lambda Task Failed" for our own debugging.
        raise RuntimeError(f"DynamoDB update_item failed during error handling: {e!s}") from e
