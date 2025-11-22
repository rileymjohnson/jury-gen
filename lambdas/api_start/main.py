import json
import logging
import os
import uuid
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sfn = boto3.client('stepfunctions')

STATE_MACHINE_ARN = os.environ.get('STATE_MACHINE_ARN')
UPLOADS_BUCKET = os.environ.get('UPLOADS_BUCKET')
if not STATE_MACHINE_ARN:
    raise RuntimeError("Missing env var STATE_MACHINE_ARN")
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

        complaint_key = payload.get('complaint_key')
        answer_key = payload.get('answer_key')
        witness_key = payload.get('witness_key')

        if not all(isinstance(x, str) and x for x in [complaint_key, answer_key, witness_key]):
            return _response(400, {'error': "'complaint_key', 'answer_key', and 'witness_key' are required"})

        # Generate a new jury_instruction_id to track this job
        jury_instruction_id = str(uuid.uuid4())

        files = {
            'complaint': {'SourceS3Path': f"s3://{UPLOADS_BUCKET}/{complaint_key}"},
            'answer': {'SourceS3Path': f"s3://{UPLOADS_BUCKET}/{answer_key}"},
            'witness': {'SourceS3Path': f"s3://{UPLOADS_BUCKET}/{witness_key}"},
        }

        input_obj = {
            'jury_instruction_id': jury_instruction_id,
            'files': files,
        }

        resp = sfn.start_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            name=jury_instruction_id,
            input=json.dumps(input_obj),
        )

        return _response(200, {
            'jury_instruction_id': jury_instruction_id,
            'executionArn': resp['executionArn'],
            'startDate': resp['startDate'].isoformat(),
        })
    except Exception as e:
        logger.exception("Failed to start execution")
        return _response(500, {'error': f'Failed to start execution: {e}'})

