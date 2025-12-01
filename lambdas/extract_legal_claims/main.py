import logging
import json
import gzip
from io import BytesIO
import boto3

# --- Import logic from the local file ---
# This works because 'claims_processing.py' is in the same folder
# and will be in the same root dir in the Lambda runtime.
import claims_processing

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")


def _load_chunks(chunks_or_pointer):
    # If already a list, return as-is
    if isinstance(chunks_or_pointer, list):
        return chunks_or_pointer
    # Pointer object cases
    if isinstance(chunks_or_pointer, dict):
        compression = chunks_or_pointer.get("Compression")
        s3obj = None
        if "S3Object" in chunks_or_pointer and isinstance(chunks_or_pointer["S3Object"], dict):
            s3obj = chunks_or_pointer["S3Object"]
        elif {"Bucket", "Key"}.issubset(set(chunks_or_pointer.keys())):
            s3obj = {"Bucket": chunks_or_pointer["Bucket"], "Key": chunks_or_pointer["Key"]}
        if s3obj:
            obj = s3.get_object(Bucket=s3obj["Bucket"], Key=s3obj["Key"])
            body = obj["Body"].read()
            if compression == "gzip" or s3obj["Key"].endswith(".gz"):
                body = gzip.decompress(body)
            chunks = json.loads(body.decode("utf-8"))
            if not isinstance(chunks, list):
                raise ValueError("Loaded chunks is not a list")
            return chunks
    raise ValueError("Invalid chunks input; expected list or S3 pointer dict")


def lambda_handler(event, context):
    """
    Extracts legal claims or counterclaims from a list of text chunks.

    1. Receives { "chunks": [...], "claim_type": "claims" } from the step.
    2. Calls the appropriate function from the 'claims_processing.py' file.
    3. Returns the list of extracted claims.
    """

    # 1. Get input from the event
    try:
        chunks = _load_chunks(event["chunks"])
        claim_type = event["claim_type"]

        if claim_type not in ["claims", "counterclaims"]:
            raise ValueError("claim_type must be 'claims' or 'counterclaims'")

    except (TypeError, KeyError, ValueError) as e:
        logger.error(f"Invalid input event: {e!s}")
        raise ValueError(f"Invalid input: {e!s}") from e

    logger.info(f"Starting extraction for '{claim_type}' with {len(chunks)} chunks.")

    # 2. Call the correct pipeline from our local module
    try:
        if claim_type == "claims":
            # 'extract_claims' runs the full (raw -> dedupe -> match) pipeline
            extracted_items = claims_processing.extract_claims(chunks)
        else:
            # 'extract_counterclaims' runs the same pipeline for counterclaims
            extracted_items = claims_processing.extract_counterclaims(chunks)

        logger.info(f"Successfully extracted {len(extracted_items)} {claim_type}.")

    except Exception as e:
        # This will catch any errors from the Bedrock calls
        logger.error(f"Failed during {claim_type} extraction: {e!s}")
        raise RuntimeError(f"Claim extraction pipeline failed: {e!s}") from e

    # 3. Return the result
    return extracted_items
