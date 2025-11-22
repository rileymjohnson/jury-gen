from supabase import create_client
import boto3

from types import SimpleNamespace
import json

bedrock = boto3.client('bedrock-runtime')

SUPABASE_URL = 'https://qeuthcemoefancllsckc.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFldXRoY2Vtb2VmYW5jbGxzY2tjIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MjUwOTM0MiwiZXhwIjoyMDc4MDg1MzQyfQ.LItXDQxd2Cjrkge3l95WA9zxOg12vcnOOhpvHYLum1M'

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)

database_claims = supabase.table('claims').select('*').execute().data
database_claims = [SimpleNamespace(**c) for c in database_claims]

def _normalize_grouped_claims(claims: list) -> list[dict]:
    """Normalize to [{'name': str, 'raw_texts': [str, ...]}]."""
    normalized: list[dict] = []
    if not isinstance(claims, list):
        return normalized
    for g in claims:
        if isinstance(g, dict):
            name = g.get('name')
            raw_texts = g.get('raw_texts')
            if raw_texts is None and isinstance(g.get('raw_text'), str):
                raw_texts = [g['raw_text']]
            if isinstance(raw_texts, str):
                raw_texts = [raw_texts]
            if name and isinstance(raw_texts, list):
                normalized.append({'name': name, 'raw_texts': raw_texts})
        elif isinstance(g, str):
            normalized.append({'name': g, 'raw_texts': []})
    return normalized

def _normalize_raw_claims(claims: list) -> list[dict]:
    """Normalize to [{'name': str, 'raw_text': str}]."""
    normalized: list[dict] = []
    if not isinstance(claims, list):
        return normalized
    for c in claims:
        if isinstance(c, dict):
            name = c.get('name')
            raw_text = c.get('raw_text')
            if isinstance(name, str) and not isinstance(raw_text, str):
                raw_text = name
            if isinstance(raw_text, str) and not isinstance(name, str):
                name = raw_text
            if isinstance(name, str) and isinstance(raw_text, str):
                normalized.append({'name': name, 'raw_text': raw_text})
        elif isinstance(c, str):
            normalized.append({'name': c, 'raw_text': c})
    return normalized

def match_claims_to_database(claims: list[dict]) -> list[dict]:
    print('ONE', claims)
    """Match extracted claims to database claims using LLM.
    
    Args:
        claims: List of {'name': str, 'raw_texts': list[str]} dicts
    
    Returns:
        List of {'claim_id': int|None, 'raw_texts': list[str]} dicts
        claim_id is None if the claim is invalid/not matched
    """
    # Format database claims for the prompt
    database_claims_text = "\n".join([
        f"ID {claim.id}: {claim.title}" + 
        (f" - {claim.description[:100]}..." if claim.description else "")
        for claim in database_claims
    ])
    print('TWO')
    # Normalize and format extracted claims
    claims = _normalize_grouped_claims(claims)
    print('THREE')
    extracted_claims_text = "\n".join([
        f"Claim {i+1}: {c['name']}\n  Raw texts: {', '.join(c.get('raw_texts', []))}"
        for i, c in enumerate(claims)
    ])
    print('FOUR')
    tools = [{
        "name": "match_claims",
        "description": "Match extracted claims to database claim IDs",
        "input_schema": {
            "type": "object",
            "properties": {
                "matches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "claim_index": {
                                "type": "integer",
                                "description": "Index of the extracted claim (1-based)"
                            },
                            "claim_id": {
                                "type": ["integer", "null"],
                                "description": "Database claim ID, or null if invalid/no match"
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "Brief explanation of the match or why it's invalid"
                            }
                        },
                        "required": ["claim_index", "claim_id"]
                    }
                }
            },
            "required": ["matches"]
        }
    }]
    print('FIVE')
    body = json.dumps({
        'anthropic_version': 'bedrock-2023-05-31',
        'max_tokens': 4000,
        'tools': tools,
        'tool_choice': {"type": "tool", "name": "match_claims"},
        'messages': [{
            'role': 'user',
            'content': f"""You are matching claims extracted from a legal complaint to a database of valid Florida legal claims.

DATABASE CLAIMS ({len(database_claims)} total):
{database_claims_text}

EXTRACTED CLAIMS TO MATCH:
{extracted_claims_text}

Your task:
1. For each extracted claim, find the best matching database claim ID
2. If a claim is invalid, not a real cause of action, or has no good match, set claim_id to null
3. Be precise - "Breach of Contract" should match the Breach of Contract ID, not something similar

Guidelines:
- Match based on legal substance, not just text similarity
- "Breach of Contract", "Contract Breach", "Breach of K" → same claim
- Invalid examples: vague claims like "Bad Behavior", "Being Mean"
- If truly uncertain between 2+ matches, choose null rather than guess
- Consider the raw texts as additional context for matching

Return matches for ALL {len(claims)} extracted claims."""
        }]
    })
    print('SIX')
    response = bedrock.invoke_model(
        body=body,
        modelId='us.anthropic.claude-3-5-sonnet-20241022-v2:0',
        accept='application/json',
        contentType='application/json'
    )
    print('SEVEN')
    response_body = json.loads(response.get('body').read())
    print('EIGHT')
    # Extract tool use result
    matches = None
    for item in response_body.get('content', []):
        if item.get('type') == 'tool_use':
            matches = item['input']['matches']
            break
    print('NINE')
    if not matches:
        # Fallback: no matches
        return [{'claim_id': None, 'raw_texts': c.get('raw_texts', [])} for c in claims]
    print('TEN')
    print('MATCHES', type(matches), matches)
    print('CLAIMS', type(claims), claims)
    if isinstance(matches, str):
        matches = json.loads(matches)
    # Build result maintaining order
    result = []
    match_dict = {m['claim_index']: m['claim_id'] for m in matches}
    
    for i, claim in enumerate(claims):
        claim_index = i + 1  # 1-based indexing
        result.append({
            'claim_id': match_dict.get(claim_index),
            'raw_texts': claim.get('raw_texts', [])
        })
    print('ELEVEN')
    return result

def deduplicate_claims(claims: list[dict]) -> list[dict]:
    """Deduplicate claims using LLM to identify same claims with different text.
    
    Args:
        claims: List of {'raw_text': str, 'name': str} dicts
    
    Returns:
        List of {'name': str, 'raw_texts': list[str]} dicts
    """
    if not claims:
        return []
    
    tools = [{
        "name": "group_duplicate_claims",
        "description": "Group claims that represent the same cause of action",
        "input_schema": {
            "type": "object",
            "properties": {
                "grouped_claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Canonical name for this claim"
                            },
                            "raw_texts": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "All raw text variants for this claim"
                            }
                        },
                        "required": ["name", "raw_texts"]
                    }
                }
            },
            "required": ["grouped_claims"]
        }
    }]
    
    # Normalize input and format claims
    claims = _normalize_raw_claims(claims)
    claims_text = "\n".join([
        f"{i+1}. Name: {c['name']}, Raw: {c['raw_text']}"
        for i, c in enumerate(claims)
    ])
    
    body = json.dumps({
        'anthropic_version': 'bedrock-2023-05-31',
        'max_tokens': 2000,
        'tools': tools,
        'tool_choice': {"type": "tool", "name": "group_duplicate_claims"},
        'messages': [{
            'role': 'user',
            'content': f"""You have extracted claims from a legal complaint using a sliding window approach. This may have created duplicates where the same claim appears multiple times with slightly different text.

Your task: Group claims that represent the SAME cause of action, even if the text differs slightly.

Claims to deduplicate:
{claims_text}

Guidelines:
- If multiple entries are clearly the same claim (e.g., "Breach of Contract" and "BREACH OF CONTRACT"), group them
- Keep all raw_text variants - they may have useful differences
- Use the clearest/most formal name as the canonical name
- Don't merge genuinely different claims (e.g., "Breach of Contract" vs "Fraud")

Return grouped claims with:
- name: canonical/best name for the claim
- raw_texts: array of all raw text variants (even if just one)"""
        }]
    })
    
    response = bedrock.invoke_model(
        body=body,
        modelId='us.anthropic.claude-3-5-sonnet-20241022-v2:0',
        accept='application/json',
        contentType='application/json'
    )
    
    response_body = json.loads(response.get('body').read())
    
    # Extract tool use result and normalize shape defensively
    for item in response_body.get('content', []):
        if item.get('type') == 'tool_use':
            grouped = item.get('input', {}).get('grouped_claims', [])
            # Normalize to list[{'name': str, 'raw_texts': list[str]}]
            normalized: list[dict] = []
            try:
                for g in grouped:
                    if isinstance(g, dict):
                        name = g.get('name')
                        raw_texts = g.get('raw_texts')
                        # Accept alternative key 'raw_text' and coerce types
                        if raw_texts is None and isinstance(g.get('raw_text'), str):
                            raw_texts = [g['raw_text']]
                        if isinstance(raw_texts, str):
                            raw_texts = [raw_texts]
                        if name and isinstance(raw_texts, list):
                            normalized.append({'name': name, 'raw_texts': raw_texts})
                    elif isinstance(g, str):
                        # Only a name was returned; keep at least the name
                        normalized.append({'name': g, 'raw_texts': []})
                if normalized:
                    return normalized
            except Exception:
                # Fall through to fallback below
                pass
    
    # Fallback: no/invalid deduplication, just reformat original claims
    return [{'name': c['name'], 'raw_texts': [c['raw_text']]} for c in claims]

def process_claim_window(previous_context: str, window_text: str, search_instructions: str) -> dict:
    """Extract claims from one window of text."""
    tools = [{
        "name": "extract_claims_and_context",
        "description": "Extract legal claims/causes of action and update analysis context",
        "input_schema": {
            "type": "object",
            "properties": {
                "updated_context": {
                    "type": "string",
                    "description": "Brief summary of what's been analyzed so far"
                },
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "raw_text": {
                                "type": "string",
                                "description": "Exact text as it appears (e.g., 'COUNT I - BREACH OF CONTRACT')"
                            },
                            "name": {
                                "type": "string",
                                "description": "Normalized claim name (e.g., 'Breach of Contract')"
                            }
                        },
                        "required": ["raw_text", "name"]
                    }
                }
            },
            "required": ["updated_context", "claims"]
        }
    }]
    
    body = json.dumps({
        'anthropic_version': 'bedrock-2023-05-31',
        'max_tokens': 1000,
        'tools': tools,
        'tool_choice': {"type": "tool", "name": "extract_claims_and_context"},
        'messages': [{
            'role': 'user',
            'content': f"""You are analyzing a legal complaint document in sliding windows.

Previous context: {previous_context}

Current window:
{window_text}

{search_instructions}

For each claim found, provide:
- raw_text: exact heading/text as written
- name: normalized claim name

Also update the context paragraph to summarize what you've seen so far."""
        }]
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
            return item['input']
    
    # Fallback if no tool use found
    return {"updated_context": previous_context, "claims": []}

def extract_raw_claims(chunks: list[str], window_size: int = 3, claim_type: str = "claims") -> list[dict]:
    """Extract claims or counterclaims from a complaint using sliding window approach.
    
    Args:
        chunks: List of text chunks (paragraphs/sections) from the complaint
        window_size: Number of chunks to process at once (default 3)
        claim_type: Either "claims" or "counterclaims"
    
    Returns:
        List of dicts with 'raw_text' and 'name' keys
    """
    all_claims = []
    
    if claim_type == "claims":
        current_context = "Beginning analysis of complaint for plaintiff's claims."
        search_instructions = """Extract any legal claims/causes of action from this window. Look for:
- COUNT headings (e.g., "COUNT I - BREACH OF CONTRACT")
- Numbered causes of action
- Claims stated in paragraphs 5-6 of complaints
- Sections labeled "COMPLAINT FOR DAMAGES" or similar"""
    else:  # counterclaims
        current_context = "Beginning analysis of complaint for defendant's counterclaims."
        search_instructions = """Extract any counterclaims/counter causes of action from this window. Look for:
- COUNTERCLAIM headings (e.g., "COUNTERCLAIM I - BREACH OF CONTRACT")
- "COUNT" sections within a COUNTERCLAIM section
- Numbered counterclaims
- Sections labeled "COUNTERCLAIM" or "DEFENDANT'S COUNTERCLAIM"
- Claims asserted by the defendant against the plaintiff"""
    
    # Slide through chunks with overlap
    for i in range(0, len(chunks), window_size - 1):
        window_chunks = chunks[i:i + window_size]
        window_text = "\n".join(window_chunks)
        
        # Process this window
        result = process_claim_window(
            previous_context=current_context,
            window_text=window_text,
            search_instructions=search_instructions
        )
        
        # Normalize and collect results defensively
        if isinstance(result, dict):
            if isinstance(result.get('updated_context'), str):
                current_context = result['updated_context']
            all_claims.extend(_normalize_raw_claims(result.get('claims', [])))
        else:
            # Unexpected shape from model; skip this window
            continue
    
    return all_claims

def extract_claims(chunks: list[str], window_size: int = 3) -> list[dict]:
    """Full pipeline: extract plaintiff's claims, deduplicate, and match to database.
    
    Returns:
        List of {'claim_id': int|None, 'raw_texts': list[str]} dicts
    """
    # Extract plaintiff's claims with sliding window
    raw_claims = extract_raw_claims(chunks, window_size, claim_type="claims")
    
    # Deduplicate
    deduplicated = deduplicate_claims(raw_claims)
    
    # Match to database
    matched = match_claims_to_database(deduplicated)
    
    return matched


def extract_counterclaims(chunks: list[str], window_size: int = 3) -> list[dict]:
    """Full pipeline: extract defendant's counterclaims, deduplicate, and match to database.
    
    Returns:
        List of {'claim_id': int|None, 'raw_texts': list[str]} dicts
    """
    # Extract defendant's counterclaims with sliding window
    raw_counterclaims = extract_raw_claims(chunks, window_size, claim_type="counterclaims")
    
    # Deduplicate
    deduplicated = deduplicate_claims(raw_counterclaims)
    
    # Match to database
    matched = match_claims_to_database(deduplicated)
    
    return matched
