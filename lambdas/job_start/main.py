import boto3
import os
import json
import datetime
import logging
import uuid  # <-- Import the UUID library

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize DynamoDB client
dynamodb = boto3.resource('dynamodb')

try:
    TABLE_NAME = os.environ['DYNAMODB_TABLE_NAME']
    table = dynamodb.Table(TABLE_NAME)
except KeyError:
    logger.error("DYNAMODB_TABLE_NAME environment variable not set.")
    raise

def lambda_handler(event, context):
    """
    Starts the jury instruction job.
    
    1. Receives the initial job payload (file paths).
    2. *Generates* a new unique jury_instruction_id.
    3. Writes a new item to DynamoDB with status "PROCESSING".
    4. Returns the *new* state, including the generated ID.
    """
    
    # The 'event' is the input from the client (e.g., from API Gateway)
    # We now expect it to *only* contain 'files'.
    try:
        files = event['files']
        if not files:
            raise KeyError("Input event must contain 'files'")

    except (TypeError, KeyError) as e:
        logger.error(f"Invalid input event. Missing 'files' key: {str(e)}")
        raise ValueError(f"Invalid input event: {str(e)}")

    # --- ID Generation ---
    # Generate a new, unique job ID
    job_id = str(uuid.uuid4())
    # ---------------------

    created_at = datetime.datetime.utcnow().isoformat()

    # This is the item we will write to DynamoDB
    db_item = {
        'jury_instruction_id': job_id,
        'status': 'PROCESSING',
        'createdAt': created_at,
        'source_files': files  # Store the input file paths
    }

    try:
        # Write the item to DynamoDB
        table.put_item(Item=db_item)
        
        logger.info(f"Successfully started job {job_id} and saved to DynamoDB.")

        # --- Critical Return Value ---
        # We must return the new job_id so the Step Function
        # (and the client) knows what it is.
        # We also pass along the original 'files' for the next step.
        return {
            'jury_instruction_id': job_id,
            'files': files
        }
        # -----------------------------

    except Exception as e:
        logger.error(f"Error starting job {job_id}. Failed to write to DynamoDB.")
        logger.error(str(e))
        raise RuntimeError(f"DynamoDB put_item failed: {str(e)}")
