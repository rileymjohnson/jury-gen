import json
import logging
import os
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sfn = boto3.client('stepfunctions')

STATE_MACHINE_ARN = os.environ.get('STATE_MACHINE_ARN')
if not STATE_MACHINE_ARN:
    raise RuntimeError("Missing env var STATE_MACHINE_ARN")


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

        files = payload.get('files')
        if not files or not isinstance(files, dict):
            return _response(400, {'error': "'files' object is required"})

        # Expect structure: {'complaint': {'SourceS3Path': 's3://...'}, 'answer': {'SourceS3Path': 's3://...'}}
        if 'complaint' not in files or 'answer' not in files:
            return _response(400, {'error': "'files' must include 'complaint' and 'answer'"})

        input_obj = { 'files': files }
        name_hint = payload.get('name')
        kwargs = { 'stateMachineArn': STATE_MACHINE_ARN, 'input': json.dumps(input_obj) }
        if name_hint:
            kwargs['name'] = name_hint

        resp = sfn.start_execution(**kwargs)
        return _response(200, {
            'executionArn': resp['executionArn'],
            'startDate': resp['startDate'].isoformat(),
        })
    except Exception as e:
        logger.exception("Failed to start execution")
        return _response(500, {'error': f'Failed to start execution: {e}'})

