import json
import logging
import os
import uuid
import urllib.parse
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client('s3')

UPLOADS_BUCKET = os.environ.get('UPLOADS_BUCKET')
if not UPLOADS_BUCKET:
    raise RuntimeError("Missing env var UPLOADS_BUCKET")


def _response(status_code: int, body: dict):
    return {
        'statusCode': status_code,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps(body),
    }


def lambda_handler(event, context):
    try:
        body = event.get('body')
        if body and isinstance(body, str):
            payload = json.loads(body)
        elif isinstance(body, dict):
            payload = body
        else:
            payload = event if isinstance(event, dict) else {}

        files = payload.get('files') or []
        if not isinstance(files, list) or not files:
            return _response(400, {'error': "'files' must be a non-empty array"})
    except Exception as e:
        logger.exception("Bad request")
        return _response(400, {'error': f'Invalid request: {e}'})

    job_id = str(uuid.uuid4())
    results = []

    for f in files:
        name = f.get('name') if isinstance(f, dict) else None
        content_type = (f.get('content_type') if isinstance(f, dict) else None) or 'application/pdf'
        if not name:
            return _response(400, {'error': "Each file must include 'name'"})

        safe_name = name.replace('..', '').replace('\n', '').replace('\r', '')
        key = f"uploads/{job_id}/{safe_name}"

        params = {
            'Bucket': UPLOADS_BUCKET,
            'Key': key,
            'ContentType': content_type,
        }
        url = s3.generate_presigned_url(
            ClientMethod='put_object',
            Params=params,
            ExpiresIn=600,
        )

        results.append({
            'name': name,
            'content_type': content_type,
            's3_bucket': UPLOADS_BUCKET,
            's3_key': key,
            's3_path': f"s3://{UPLOADS_BUCKET}/{key}",
            'presigned_url': url,
        })

    return _response(200, {'job_id': job_id, 'uploads': results})

