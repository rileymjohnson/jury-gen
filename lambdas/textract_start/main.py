import boto3
import os
import json
import logging
import time
import urllib.parse

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize Boto3 clients
# These will use the Lambda's IAM execution role
s3 = boto3.client('s3')
textract = boto3.client('textract')

# Get the processing bucket name from an environment variable
try:
    # This is the S3 bucket that Textract has permission to read from.
    PROCESSING_BUCKET = os.environ['PROCESSING_BUCKET_NAME']
except KeyError:
    logger.error("PROCESSING_BUCKET_NAME environment variable not set.")
    raise

def lambda_handler(event, context):
    """
    Starts the Textract job for a single document.
    
    1. Receives the S3 path of the *source* document.
    2. Copies the document to a *processing* S3 bucket.
    3. Starts the 'start_document_text_detection' job on the copied file.
    4. Returns the JobId and the path to the temporary file for later cleanup.
    """
    
    # 1. Get the source S3 path from the input event
    try:
        source_s3_path = event['SourceS3Path']
        # S3 paths look like "s3://bucket-name/path/to/file.pdf"
        # We need to parse this into bucket and key
        
        parsed_url = urllib.parse.urlparse(source_s3_path)
        source_bucket = parsed_url.netloc
        source_key = parsed_url.path.lstrip('/')
        
        if not source_bucket or not source_key:
            raise ValueError("Invalid SourceS3Path format")

    except (TypeError, KeyError, ValueError) as e:
        logger.error(f"Invalid input event. Expected {{'SourceS3Path': '...'}}: {str(e)}")
        raise ValueError(f"Invalid input event: {str(e)}")

    # 2. Copy the file to the processing bucket
    try:
        # Create a unique key for the processing bucket
        # e.g., "complaint.pdf-1678886400.pdf"
        file_name = source_key.split('/')[-1]
        dest_key = f"processing/{file_name}-{int(time.time())}"
        
        copy_source = {
            'Bucket': source_bucket,
            'Key': source_key
        }
        
        logger.info(f"Copying {source_bucket}/{source_key} to {PROCESSING_BUCKET}/{dest_key}...")
        
        s3.copy_object(
            Bucket=PROCESSING_BUCKET,
            Key=dest_key,
            CopySource=copy_source
        )
        
        logger.info("Copy successful.")
        # Small delay to ensure object availability across services
        time.sleep(1)

    except Exception as e:
        logger.error(f"Failed to copy S3 object: {str(e)}")
        raise RuntimeError(f"S3 copy failed: {str(e)}")

    # 3. Start the Textract job
    try:
        logger.info(f"Starting Textract job for {PROCESSING_BUCKET}/{dest_key}...")

        response = textract.start_document_text_detection(
            DocumentLocation={
                'S3Object': {
                    'Bucket': PROCESSING_BUCKET,
                    'Name': dest_key
                }
            }
        )
        
        job_id = response.get('JobId')
        if not job_id:
            raise RuntimeError("Textract response missing JobId")
            
        logger.info(f"Textract job started with JobId: {job_id}")

    except Exception as e:
        logger.error(f"Failed to start Textract job: {str(e)}")
        # Clean up the temp file if the job fails to start
        # try:
        #     s3.delete_object(Bucket=PROCESSING_BUCKET, Key=dest_key)
        # except Exception as e_del:
        #     logger.error(f"Failed to clean up temp file {dest_key}: {e_del}")
        raise RuntimeError(f"Textract job start failed: {str(e)}")

    # 4. Return the JobId and the temp file path
    # This output will be used by the next steps in the state machine.
    return {
        'JobId': job_id,
        'TempS3Object': {
            'Bucket': PROCESSING_BUCKET,
            'Key': dest_key
        }
    }
