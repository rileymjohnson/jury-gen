import datetime
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
    Starts the jury instruction job.

    1. Receives the initial job payload (file paths).
    2. Expects a provided 'jury_instruction_id' from the caller (Edge Function/API).
    3. Writes a new item to DynamoDB with status "PROCESSING".
    4. Returns the state including the provided ID.
    """

    # The 'event' is the input from the Step Function start (via API/Edge Function)
    # We now expect it to contain both 'jury_instruction_id' and 'files'.
    try:
        job_id = event["jury_instruction_id"]
        files = event["files"]
        config = event.get("config")
        if not isinstance(config, dict):
            raise ValueError("'config' is required and must be an object")
        if not job_id:
            raise KeyError("Input event must contain 'jury_instruction_id'")
        if not files:
            raise KeyError("Input event must contain 'files'")

    except (TypeError, KeyError) as e:
        logger.error(f"Invalid input event. Missing 'files' key: {e!s}")
        raise ValueError(f"Invalid input event: {e!s}") from e

    created_at = datetime.datetime.utcnow().isoformat()

    # This is the item we will write to DynamoDB
    db_item = {
        "jury_instruction_id": job_id,
        "status": "PROCESSING",
        "createdAt": created_at,
        "source_files": files,  # Store the input file paths
        "config": config,
    }

    try:
        # Write the item to DynamoDB
        table.put_item(Item=db_item)

        logger.info(f"Successfully started job {job_id} and saved to DynamoDB.")

        # Return the provided job_id so the Step Function and downstream tasks
        # can correlate updates and results.
        return {"jury_instruction_id": job_id, "files": files, "config": config}
        # -----------------------------

    except Exception as e:
        logger.error(f"Error starting job {job_id}. Failed to write to DynamoDB.")
        logger.error(str(e))
        raise RuntimeError(f"DynamoDB put_item failed: {e!s}") from e
