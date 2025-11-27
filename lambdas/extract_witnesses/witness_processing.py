import json

import boto3

bedrock = boto3.client("bedrock-runtime")


def extract_witnesses(witness_list_chunks: list[str]) -> list[dict]:
    """Extract witness names from a witness list document.

    Args:
        witness_list_chunks: List of text chunks from the witness list document

    Returns:
        List of dicts with structure:
        [
            {'first_name': str, 'last_name': str},
            ...
        ]
    """
    # Combine all chunks for witness extraction
    full_text = "\n".join(witness_list_chunks)

    tools = [
        {
            "name": "extract_witness_names",
            "description": "Extract witness names from a witness list",
            "input_schema": {
                "type": "object",
                "properties": {
                    "witnesses": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "first_name": {"type": "string", "description": "First name of the witness"},
                                "last_name": {"type": "string", "description": "Last name of the witness"},
                            },
                            "required": ["first_name", "last_name"],
                        },
                    }
                },
                "required": ["witnesses"],
            },
        }
    ]

    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "tools": tools,
            "tool_choice": {"type": "tool", "name": "extract_witness_names"},
            "messages": [
                {
                    "role": "user",
                    "content": f"""You are extracting witness names from a witness list document.

Document text:
{full_text}

Extract all individual witness names. Look for:
- Numbered lists of witnesses (e.g., "1. Richard Gold", "2. Marta Gold")
- Names followed by addresses
- Names in lists or tables

DO NOT include:
- Generic/placeholder entries like "Any and all individuals identified in discovery"
- "Defendant reserves the right..." or "Plaintiff reserves the right..." statements
- Attorney names unless clearly listed as witnesses
- Names in certificate of service sections (unless also listed as witnesses)
- Names only appearing in headers/footers

For each witness, extract:
- first_name: The person's first name
- last_name: The person's last name

Return all individual witnesses found.""",
                }
            ],
        }
    )

    response = bedrock.invoke_model(
        body=body,
        modelId="us.anthropic.claude-3-5-sonnet-20241022-v2:0",
        accept="application/json",
        contentType="application/json",
    )

    response_body = json.loads(response.get("body").read())

    # Extract tool use result
    for item in response_body.get("content", []):
        if item.get("type") == "tool_use":
            witnesses = item["input"]["witnesses"]

            # Deduplicate witnesses (same first and last name)
            seen = set()
            unique_witnesses = []
            for witness in witnesses:
                key = (witness["first_name"].lower(), witness["last_name"].lower())
                if key not in seen:
                    seen.add(key)
                    unique_witnesses.append(witness)

            return unique_witnesses

    # Fallback if no tool use found
    return []
