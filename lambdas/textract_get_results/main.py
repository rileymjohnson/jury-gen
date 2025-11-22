import boto3
import os
import json
import logging
import nltk  # <-- Just import it
from nltk.tokenize import sent_tokenize

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize Boto3 clients
textract = boto3.client('textract')
s3 = boto3.client('s3')

#
# NO MORE NLTK DOWNLOAD HACKS NEEDED!
# The 'punkt' data is already in the container's
# default search path.
#

def extract_text_chunks(text: str, max_chunk_tokens: int = 2000) -> list[str]:
    """
    Chunks text by grouping sentences up to a max token limit.
    This is the fast, non-Bedrock version.
    """
    try:
        # This will just work
        sentences = sent_tokenize(text)
    except Exception as e:
        logger.error(f"Failed to tokenize text, falling back to simple split: {e}")
        sentences = text.split('\n')

    chunks = []
    current_chunk = []
    current_length = 0
    
    for sentence in sentences:
        sentence_length = len(sentence.split())
        
        if sentence_length > max_chunk_tokens:
            if current_chunk:
                chunks.append(" ".join(current_chunk))
            chunks.append(sentence)
            current_chunk = []
            current_length = 0
            continue

        if current_length + sentence_length > max_chunk_tokens:
            chunks.append(" ".join(current_chunk))
            current_chunk = [sentence]
            current_length = sentence_length
        else:
            current_chunk.append(sentence)
            current_length += sentence_length
    
    if current_chunk:
        chunks.append(" ".join(current_chunk))
        
    return chunks


def lambda_handler(event, context):
    """
    Gets the full text from a completed Textract job, chunks it,
    and cleans up the temporary S3 file.
    """
    
    # 1. Get JobId and temp file info (NO CHANGE HERE)
    try:
        job_id = event['JobId']
        temp_s3_object = event['TempS3Object']
        temp_bucket = temp_s3_object['Bucket']
        temp_key = temp_s3_object['Key']

    except (TypeError, KeyError) as e:
        logger.error(f"Invalid input event. Missing required keys: {str(e)}")
        raise ValueError(f"Invalid input event: {str(e)}")

    all_text_lines = []
    
    # 2. Paginate through all Textract results (NO CHANGE HERE)
    try:
        logger.info(f"Fetching results for Textract JobId: {job_id}...")
        next_token = None
        while True:
            kwargs = {'JobId': job_id}
            if next_token:
                kwargs['NextToken'] = next_token
            
            response = textract.get_document_text_detection(**kwargs)
            
            blocks = response.get('Blocks', [])
            for block in blocks:
                if block.get('BlockType') == 'LINE':
                    all_text_lines.append(block.get('Text', ''))
            
            next_token = response.get('NextToken')
            if not next_token:
                break
        
        logger.info(f"Successfully fetched all {len(all_text_lines)} lines of text.")

    except Exception as e:
        logger.error(f"Failed to get Textract results for job {job_id}: {str(e)}")
        raise RuntimeError(f"Textract GetResults failed: {str(e)}")
    
    # 3. Clean up the temporary S3 file (NO CHANGE HERE)
    finally:
        try:
            logger.info(f"Cleaning up temporary file: {temp_bucket}/{temp_key}")
            s3.delete_object(Bucket=temp_bucket, Key=temp_key)
            logger.info("Cleanup successful.")
        except Exception as e:
            logger.error(f"Failed to clean up S3 object {temp_key}: {str(e)}")

    # 4. Combine and chunk the text (NO CHANGE HERE)
    if not all_text_lines:
        logger.warning(f"No text lines found for job {job_id}. Returning empty list.")
        return []

    full_text = "\n".join(all_text_lines)
    
    try:
        chunks = extract_text_chunks(full_text)
        logger.info(f"Successfully chunked text into {len(chunks)} chunks.")
    except Exception as e:
        logger.error(f"Failed to chunk text: {e}")
        raise RuntimeError(f"Text chunking failed: {str(e)}")

    # 5. Return the chunks (NO CHANGE HERE)
    return chunks
