import json
import logging
import os
import uuid

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")

UPLOADS_BUCKET = os.environ.get("UPLOADS_BUCKET")
if not UPLOADS_BUCKET:
    raise RuntimeError("Missing env var UPLOADS_BUCKET")


def _response(status_code: int, body: dict):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _presign_put(key: str, content_type: str = "application/pdf", expires_in: int = 600) -> dict:
    url = s3.generate_presigned_url(
        ClientMethod="put_object",
        Params={"Bucket": UPLOADS_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=expires_in,
    )
    return {
        "bucket": UPLOADS_BUCKET,
        "key": key,
        "s3_path": f"s3://{UPLOADS_BUCKET}/{key}",
        "presigned_url": url,
        "content_type": content_type,
        "expires_in": expires_in,
    }


def lambda_handler(event, context):
    try:
        # No input required. Generate three presigned URLs for client uploads.
        upload_id = str(uuid.uuid4())
        base_prefix = f"uploads/{upload_id}"

        complaint = _presign_put(f"{base_prefix}/complaint.pdf")
        answer = _presign_put(f"{base_prefix}/answer.pdf")
        witness = _presign_put(f"{base_prefix}/witness.pdf")

        return _response(
            200,
            {
                "upload_id": upload_id,
                "uploads": {
                    "complaint": complaint,
                    "answer": answer,
                    "witness": witness,
                },
            },
        )
    except Exception as e:
        logger.exception("Failed to create presigned URLs")
        return _response(500, {"error": f"Failed to create presigned URLs: {e}"})
