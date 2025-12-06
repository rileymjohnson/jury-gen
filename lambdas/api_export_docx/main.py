import base64
from io import BytesIO
import json
import logging
import os

import boto3
from docx import Document

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME")
if not TABLE_NAME:
    raise RuntimeError("Missing env var DYNAMODB_TABLE_NAME")
table = dynamodb.Table(TABLE_NAME)


def _response(status_code: int, body: dict, *, headers: dict | None = None):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", **(headers or {})},
        "body": json.dumps(body),
    }


def build_docx(instructions: list[dict]) -> bytes:
    doc = Document()
    doc.add_heading("Jury Instructions", level=1)

    for item in instructions:
        if not isinstance(item, dict):
            continue
        number = str(item.get("number", "")).strip()
        text = str(item.get("customized_text", "")).strip()
        if not (number or text):
            continue
        para = doc.add_paragraph()
        if number:
            para.add_run(f"{number}. ").bold = True
        para.add_run(text)

    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def lambda_handler(event, context):
    try:
        path_params = event.get("pathParameters") or {}
        job_id = path_params.get("id") or path_params.get("job_id")
        if not job_id:
            return _response(400, {"error": "Missing id in path"})

        res = table.get_item(Key={"jury_instruction_id": job_id})
        item = res.get("Item")
        if not item:
            return _response(404, {"error": "Record not found"})

        status = item.get("status")
        if status != "COMPLETE":
            return _response(409, {"error": f"Record is not complete (status={status})"})

        instructions = item.get("jury_instructions_text") or []
        if not isinstance(instructions, list):
            return _response(500, {"error": "Invalid instructions format"})

        docx_bytes = build_docx(instructions)
        b64 = base64.b64encode(docx_bytes).decode("ascii")

        filename = f"JuryInstructions-{job_id}.docx"
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "Content-Disposition": f"attachment; filename=\"{filename}\"",
            },
            "isBase64Encoded": True,
            "body": b64,
        }
    except Exception as e:
        logger.exception("Failed to generate docx")
        return _response(500, {"error": f"Failed to generate document: {e}"})
