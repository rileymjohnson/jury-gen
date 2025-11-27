import logging

# --- Import logic from the local file ---
# This works because 'claims_processing.py' is in the same folder
# and will be in the same root dir in the Lambda runtime.
import claims_processing

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """
    Extracts legal claims or counterclaims from a list of text chunks.

    1. Receives { "chunks": [...], "claim_type": "claims" } from the step.
    2. Calls the appropriate function from the 'claims_processing.py' file.
    3. Returns the list of extracted claims.
    """

    # 1. Get input from the event
    try:
        chunks = event["chunks"]
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
