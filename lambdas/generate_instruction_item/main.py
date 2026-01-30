import logging

import instruction_processing

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _unique_by_number(instructions: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for inst in instructions or []:
        num = (inst or {}).get("number")
        if num and num not in seen:
            seen.add(num)
            out.append(inst)
        elif not num:
            # Keep items without numbers (e.g., some custom outputs)
            out.append(inst)
    return out


def lambda_handler(event, _context):
    """
    Generate instructions for a single item (claim or counterclaim).

    Input:
      {
        "type": "claim" | "counterclaim",
        "item": { "claim_id": str, "defenses": [...], "damages": {...} },
        "case_facts": str,
        "config": { ... }
      }

    Output:
      {
        "instructions": [ ... ],
        "processed_item": { "type": str, "claim_id": str, "category": str }
      }
    """
    try:
        item_type = event.get("type")
        item = event.get("item") or {}
        case_facts = event.get("case_facts") or ""
        claim_id = item.get("claim_id")
        if item_type not in ("claim", "counterclaim"):
            raise ValueError("'type' must be 'claim' or 'counterclaim'")
        if not claim_id:
            raise ValueError("item.claim_id is required")
    except Exception as e:
        logger.error(f"Invalid input: {e}")
        raise

    claim = instruction_processing.database_get_claim_by_id(claim_id)
    if not claim:
        logger.warning(f"Claim not found in database: {claim_id}")
        return {"instructions": [], "processed_item": {"type": item_type, "claim_id": claim_id, "category": None}}

    # Preload available standard categories from DynamoDB once per invoke
    all_sji = instruction_processing._scan_all(instruction_processing._sji_table)
    standard_instruction_categories = sorted(
        {
            (r.get("category_number"), r.get("category_title"))
            for r in all_sji
            if r.get("category_number") and r.get("category_title")
        }
    )

    category = instruction_processing.match_claim_to_category(
        claim_title=claim.get("title"),
        case_facts=case_facts,
        standard_categories=standard_instruction_categories,
    )

    out_instructions: list[dict] = []

    # 4xx or custom per item
    if category != "CUSTOM":
        sel = instruction_processing.select_and_customize_instructions(
            category_number=category,
            claim=claim,
            claim_elements=claim.get("elements"),
            defenses=(item.get("defenses", []) if item_type == "claim" else []),
            case_facts=case_facts,
            damages=item.get("damages", {}),
        )
        out_instructions.extend(sel)
    else:
        cust = instruction_processing.generate_custom_instructions(
            claim_info=item, claim=claim, case_facts=case_facts
        )
        if cust:
            out_instructions.append(cust)

    # 5xx damages per item - deterministic from claim mapping (with filtering)
    try:
        flags = item.get("damages", {}) if isinstance(item, dict) else {}
        mapping = (claim or {}).get("damages") or {}
        selected_numbers = list(mapping.get("damages_instructions") or [])
        # Filter out 501/502 personal injury / wrongful death chapters for non-injury categories
        cat = ((mapping.get("claim_category") or (claim or {}).get("claim_category") or "").lower()
               if isinstance(mapping, dict) else "")
        def _is_injury_cat(s: str) -> bool:
            s = (s or "").lower()
            return any(w in s for w in ("injury", "medical"))
        if not _is_injury_cat(cat):
            selected_numbers = [n for n in selected_numbers if not str(n).startswith(("501", "502"))]
        if mapping.get("allows_punitive") and bool(flags.get("seeks_punitive")) and "503.1" not in selected_numbers:
            selected_numbers.append("503.1")
        for num in selected_numbers:
            rendered = instruction_processing._render_instruction_by_number(str(num), inputs={})
            if rendered:
                out_instructions.append(rendered)
    except Exception:
        # Don't fail the item for damages stage
        pass

    out_instructions = _unique_by_number(out_instructions)

    return {
        "instructions": out_instructions,
        "processed_item": {"type": item_type, "claim_id": claim_id, "category": category},
    }
