import logging

import boto3

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize Boto3 client
textract = boto3.client("textract")


def lambda_handler(event, context):
    """
    Checks the status of a running Textract job.

    1. Receives the Textract JobId from the input event.
    2. Calls 'get_document_text_detection' to get the job's status.
    3. Returns the status, which the Step Function Choice state will use.
    """

    # 1. Get the JobId from the input event
    # The Step Function will pass the output of the 'textract_start'
    # function to this one. We only care about the 'JobId' field.
    try:
        job_id = event["JobId"]
        if not job_id:
            raise KeyError("Input event missing 'JobId'")

    except (TypeError, KeyError) as e:
        logger.error(f"Invalid input event. Expected {{'JobId': '...'}}: {e!s}")
        raise ValueError(f"Invalid input event: {e!s}") from e

    # 2. Call the Textract API
    try:
        logger.info(f"Checking status for Textract JobId: {job_id}...")

        response = textract.get_document_text_detection(JobId=job_id)

        job_status = response.get("JobStatus")

        if not job_status:
            raise RuntimeError("Textract response missing JobStatus")

        logger.info(f"Job status is: {job_status}")

    except Exception as e:
        logger.error(f"Failed to check status for Textract job {job_id}: {e!s}")
        # Let the Step Function handle this as a retryable error
        raise RuntimeError(f"Textract GetJobStatus failed: {e!s}") from e

    # 3. Return *only* the status.
    # The Step Function's Choice state will evaluate this simple output.
    # We also pass the original event payload through so we don't
    # lose the JobId or TempS3Object on the next loop.

    # Merge the original event with the new status
    event["Status"] = job_status

    return event
