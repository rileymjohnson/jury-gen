import boto3

import json

bedrock = boto3.client('bedrock-runtime')

def update_case_facts(current_facts, new_content, source):
    """
    Update case facts based on new content window
    
    Args:
        current_facts: Current state of case facts (empty string on first call)
        new_content: New chunk(s) of document text
        source: Source document name for context
        
    Returns:
        str: Updated case facts
    """
    tools = [{
        "name": "update_facts",
        "description": "Update the case facts summary based on new information",
        "input_schema": {
            "type": "object",
            "properties": {
                "updated_facts": {
                    "type": "string",
                    "description": "The updated case facts summary (2-3 paragraphs)"
                }
            },
            "required": ["updated_facts"]
        }
    }]
    
    if not current_facts:
        instruction = """Start building a case facts summary. Write 2-3 paragraphs covering:
- Who the parties are and their relationship
- What contract/agreement exists (if any)
- What happened (key events, timeline)
- What the plaintiff alleges
- What the defendant's position is

Write in past tense, neutral tone."""
    else:
        instruction = """Update the existing case facts by:
- ADDING new relevant information you see
- EDITING if new content clarifies or contradicts existing facts
- DELETING irrelevant or incorrect information
- Keep it to 2-3 paragraphs total

Write in past tense, neutral tone."""
    
    prompt = f"""You are building a case facts summary for jury instructions.

CURRENT CASE FACTS:
{current_facts if current_facts else '[No facts yet]'}

---

NEW CONTENT from {source}:
{new_content}

---

{instruction}"""

    body = json.dumps({
        'anthropic_version': 'bedrock-2023-05-31',
        'max_tokens': 1500,
        'tools': tools,
        'tool_choice': {"type": "tool", "name": "update_facts"},
        'messages': [{'role': 'user', 'content': prompt}]
    })
    
    response = bedrock.invoke_model(
        body=body,
        modelId='us.anthropic.claude-3-5-sonnet-20241022-v2:0',
        accept='application/json',
        contentType='application/json'
    )
    
    response_body = json.loads(response.get('body').read())
    
    # Extract tool use result
    for item in response_body.get('content', []):
        if item.get('type') == 'tool_use':
            return item['input']['updated_facts']
    
    # Fallback if no tool use found
    return current_facts

def extract_case_facts(complaint_chunks, answer_chunks, witness_chunks=None):
    """
    Extract case facts by sliding over document chunks and iteratively
    building/refining a 2-3 paragraph summary
    
    Args:
        complaint_chunks: List of text chunks from complaint
        answer_chunks: List of text chunks from answer/counterclaim
        witness_chunks: Optional list of text chunks from witness list
        
    Returns:
        str: 2-3 paragraph case facts summary
    """
    case_facts = ""
    
    # Process complaint chunks
    print("Processing complaint...")
    for i in range(0, len(complaint_chunks), 2):  # sliding window with overlap
        window = "\n".join(complaint_chunks[i:i+3])
        case_facts = update_case_facts(case_facts, window, "complaint")
    
    # Process answer chunks
    print("Processing answer...")
    for i in range(0, len(answer_chunks), 2):
        window = "\n".join(answer_chunks[i:i+3])
        case_facts = update_case_facts(case_facts, window, "answer")
    
    # Process witness list if provided
    if witness_chunks:
        print("Processing witness list...")
        for i in range(0, len(witness_chunks), 2):
            window = "\n".join(witness_chunks[i:i+3])
            case_facts = update_case_facts(case_facts, window, "witness list")
    
    print("Case facts extraction complete!")
    return case_facts
