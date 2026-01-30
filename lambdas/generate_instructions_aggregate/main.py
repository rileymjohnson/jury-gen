import logging
import re

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
            out.append(inst)
    return out


def _extract_party_names(config: dict, case_facts: str) -> tuple[str, str]:
    """Return best-guess (plaintiff, defendant) names.

    Prefer config if provided and not obvious placeholders; otherwise, try to
    parse from case_facts using a few robust patterns (caption or narrative).
    """
    cfg_p = (config or {}).get("plaintiff_name") or ""
    cfg_d = (config or {}).get("defendant_name") or ""

    placeholders = {"john doe", "jane doe", "rachel rowe", "plaintiff", "defendant"}

    def norm(x: str) -> str:
        return str(x or "").strip()

    def is_placeholder(x: str) -> bool:
        n = norm(x)
        return not n or n.lower() in placeholders

    def titleize(x: str) -> str:
        x = norm(x)
        # Handle ALL CAPS names common in captions
        if x.isupper():
            x = x.title()
        return x

    p = cfg_p
    d = cfg_d

    # Try caption pattern: "JENNIFER GOLD, Plaintiff, ... vs. ROGER GOLD, Defendant"
    if (is_placeholder(p) or is_placeholder(d)) and isinstance(case_facts, str):
        caps_pl = re.search(r"([A-Z][A-Z '\-]+),\s*Plaintiff", case_facts)
        caps_df = re.search(r"([A-Z][A-Z '\-]+),\s*Defendant", case_facts)
        if caps_pl and is_placeholder(p):
            p = titleize(caps_pl.group(1))
        if caps_df and is_placeholder(d):
            d = titleize(caps_df.group(1))

    # Try narrative pattern: "([Name]) filed a complaint ... against ([Name])"
    if (is_placeholder(p) or is_placeholder(d)) and isinstance(case_facts, str):
        narr = re.search(
            r"([A-Z][a-z]+(?: [A-Z][a-z]+){0,3})\s+(?:filed|brought)\s+.*?\s+against\s+([A-Z][a-z]+(?: [A-Z][a-z]+){0,3})",  # noqa: E501
            case_facts,
        )
        if narr:
            if is_placeholder(p):
                p = norm(narr.group(1))
            if is_placeholder(d):
                d = norm(narr.group(2))

    # Always prefer names parsed from case_facts when available (override config)
    if isinstance(case_facts, str):
        caps_pl2 = re.search(r"([A-Z][A-Z '\-]+),\s*Plaintiff", case_facts)
        caps_df2 = re.search(r"([A-Z][A-Z '\-]+),\s*Defendant", case_facts)
        if caps_pl2:
            p = titleize(caps_pl2.group(1))
        if caps_df2:
            d = titleize(caps_df2.group(1))
        if not (caps_pl2 and caps_df2):
            narr2 = re.search(
                r"([A-Z][a-z]+(?: [A-Z][a-z]+){0,3})\s+(?:filed|brought)\s+.*?\s+against\s+([A-Z][a-z]+(?: [A-Z][a-z]+){0,3})",  # noqa: E501
                case_facts,
            )
            if narr2:
                p = titleize(narr2.group(1))
                d = titleize(narr2.group(2))

    # Final fallbacks
    p = titleize(p or "Plaintiff") or "Plaintiff"
    d = titleize(d or "Defendant") or "Defendant"
    return p, d


def _liability_question_for(category: str, title: str, claimant: str, defendant: str) -> str:
    cat = (category or "").lower()
    base = (title or "the claim").strip()
    templates = {
        "contract": f"Did {defendant} breach the contract with {claimant}, and was that breach a legal cause of damage to {claimant}?",  # noqa: E501
        "tort": f"Was there {base.lower()} on the part of {defendant} which was a legal cause of damage to {claimant}?",
        "defamation": f"Did {defendant} make a false and defamatory statement about {claimant}, publish it to a third party, and was {claimant} damaged as a result?",  # noqa: E501
        "fraud": f"Did {claimant} prove by clear and convincing evidence that {defendant} committed fraud against {claimant}?",  # noqa: E501
        "fiduciary": f"Did {defendant} breach a fiduciary duty owed to {claimant}, and was that breach a legal cause of damage to {claimant}?",  # noqa: E501
        "conversion": f"Did {defendant} commit conversion of {claimant}'s property?",
        "equitable": f"Is {claimant} entitled to {base.lower()}?",
    }
    return templates.get(cat, f"Did {defendant} commit {base.lower()} against {claimant}?")


def _build_claim_block(item: dict, claimant: str, defendant: str, start_q: int) -> tuple[dict, int]:
    q = start_q
    claim_id = item.get("claim_id")
    db_claim = instruction_processing.database_get_claim_by_id(claim_id) or {}
    title = db_claim.get("title") or item.get("claim_title") or "Unknown"
    category = ((db_claim.get("damages") or {}).get("claim_category") or db_claim.get("claim_category") or "unknown")

    questions: list[dict] = []

    # 1) Liability
    liability_text = _liability_question_for(category, title, claimant, defendant)
    questions.append({
        "number": q,
        "text": liability_text,
        "type": "liability",
        "response_type": "yes_no",
        "if_no": f"Verdict for {defendant}. Skip to next claim.",
        "if_yes": "Continue to next question.",
    })
    q += 1

    # 2) Applicable defenses (for plaintiff's claims; counterclaims have none in current workflow)
    applicable = []
    for d in (item.get("defenses") or []):
        applies_ids = d.get("applies_to_claims") or []
        if claim_id in applies_ids:
            applicable.append(d)

    complete_defs = [d for d in applicable if (d.get("type") or "complete") == "complete"]
    # Only include setoff for contract claims; suppress for others (e.g., defamation)
    setoff_defs = []
    if (category or "").lower() == "contract":
        setoff_defs = [d for d in applicable if (d.get("type") or "") == "setoff"]

    defense_start = q
    for d in complete_defs:
        questions.append({
            "number": q,
            "text": f"Did {defendant} prove {d.get('name','').lower()}?",
            "type": "defense",
            "defense_name": d.get("name"),
            "response_type": "yes_no",
        })
        q += 1

    if complete_defs:
        count = len(complete_defs)
        if count == 1:
            questions.append({
                "type": "instruction",
                "text": f"If YES to question {defense_start}, verdict for {defendant}. If NO, continue.",
            })
        else:
            questions.append({
                "type": "instruction",
                "text": f"If YES to any of questions {defense_start}-{q-1}, verdict for {defendant}. If NO to all, continue.",  # noqa: E501
            })

    for d in setoff_defs:
        questions.append({
            "number": q,
            "text": f"Did {defendant} prove a right to setoff?",
            "type": "setoff",
            "defense_name": d.get("name"),
            "response_type": "yes_no",
            "followup": "If YES, state amount: $________",
        })
        q += 1

    # 3) Damages (skip for equitable claims)
    damages_block = None
    if (category or "").lower() != "equitable":
        damages_block = {
            "question": f"What is the total amount of {claimant}'s damages?",
            "response_type": "amount",
            "number": q,
        }
        q += 1
        if bool((item.get("damages") or {}).get("seeks_punitive")):
            damages_block["punitive"] = {
                "question": "Do you award punitive damages?",
                "followup": "If YES, state amount: $________",
                "response_type": "yes_no",
                "number": q,
            }
            q += 1

    block = {
        "claim_id": claim_id,
        "claim_title": title,
        "claimant": claimant,
        "defendant": defendant,
        "questions": questions,
    }
    if damages_block:
        block["damages"] = damages_block

    return block, q


def _generate_verdict_form(claims: list[dict], counterclaims: list[dict], case_facts: str, config: dict) -> dict:
    plaintiff, defendant = _extract_party_names(config, case_facts)
    sections: list[dict] = []
    qnum = 1
    has_negligence = False

    # Plaintiff's claims
    p_claims: list[dict] = []
    for c in claims or []:
        blk, qnum = _build_claim_block(c, claimant=plaintiff, defendant=defendant, start_q=qnum)
        p_claims.append(blk)
        db_claim = instruction_processing.database_get_claim_by_id(c.get("claim_id")) or {}
        cat = ((db_claim.get("damages") or {}).get("claim_category") or db_claim.get("claim_category") or "").lower()
        title_l = (db_claim.get("title") or "").lower()
        if cat == "negligence" or ("negligence" in title_l) or ("negligent" in title_l):
            has_negligence = True
    sections.append({"title": "PLAINTIFF'S CLAIMS", "claims": p_claims})

    # Defendant's counterclaims
    if counterclaims:
        d_claims: list[dict] = []
        for c in counterclaims or []:
            blk, qnum = _build_claim_block(c, claimant=defendant, defendant=plaintiff, start_q=qnum)
            d_claims.append(blk)
            db_claim = instruction_processing.database_get_claim_by_id(c.get("claim_id")) or {}
            cat = ((db_claim.get("damages") or {}).get("claim_category") or db_claim.get("claim_category") or "").lower()  # noqa: E501
            title_l = (db_claim.get("title") or "").lower()
            if cat == "negligence" or ("negligence" in title_l) or ("negligent" in title_l):
                has_negligence = True
        sections.append({"title": "DEFENDANT'S COUNTERCLAIMS", "claims": d_claims})

    if has_negligence:
        sections.append({
            "title": "APPORTIONMENT OF FAULT",
            "type": "apportionment",
            "instruction": "If you found negligence, state percentage of fault. Total must equal 100%.",
            "parties": [plaintiff, defendant],
        })

    return {"plaintiff": plaintiff, "defendant": defendant, "sections": sections}


def lambda_handler(event, _context):  # noqa: PLR0912, PLR0915
    """
    Aggregate per-item instruction results and add 100s/200s and 600s series.

    Input:
      {
        "claim_results": [ {"instructions":[...], "processed_item": {...}}, ... ],
        "counterclaim_results": [ ... ],
        "case_facts": str,
        "witnesses": [ {first_name,last_name} ],
        "config": {...},
        "claims": [ ... ],
        "counterclaims": [ ... ]
      }

    Output:
      [ { number, customized_text, ... }, ... ]
    """
    claim_results = event.get("claim_results") or []
    counterclaim_results = event.get("counterclaim_results") or []
    case_facts = event.get("case_facts") or ""
    witnesses = event.get("witnesses") or []
    config = event.get("config") or {}
    claims = event.get("claims") or []
    counterclaims = event.get("counterclaims") or []

    all_instructions: list[dict] = []

    # Normalize party names across config using case_facts (avoid placeholders)
    try:
        _p, _d = _extract_party_names(config, case_facts)
        config = {**config, "plaintiff_name": _p, "defendant_name": _d}
    except Exception:
        pass

    # 201.1 (+ optional 101.1) and then 201.2, 201.3
    try:
        parts_201_1 = instruction_processing._generate_201_1(
            config=config, case_facts=case_facts, witnesses=witnesses
        )
        if parts_201_1:
            include_oath = bool(config.get("include_so_help_you_god", False))
            pre = [x for x in parts_201_1 if not (x.get("meta") or {}).get("is_continuation_part")]
            post = [x for x in parts_201_1 if (x.get("meta") or {}).get("is_continuation_part")]
            if include_oath:
                all_instructions.extend(pre)
                oath = instruction_processing._generate_101_1(config=config)
                if oath:
                    all_instructions.append(oath)
                all_instructions.extend(post)
            else:
                all_instructions.extend(parts_201_1)
    except Exception:
        pass

    try:
        si_201_2 = instruction_processing._generate_201_2(config=config)
        if si_201_2:
            all_instructions.append(si_201_2)
    except Exception:
        pass

    try:
        si_201_3 = instruction_processing._generate_201_3()
        if si_201_3:
            all_instructions.append(si_201_3)
    except Exception:
        pass

    # Flatten per-item outputs
    item_instructions = []
    for r in claim_results:
        item_instructions.extend((r or {}).get("instructions") or [])
    for r in counterclaim_results:
        item_instructions.extend((r or {}).get("instructions") or [])

    # Split non-5xx and 5xx to preserve ordering similar to original pipeline
    non_5xx = []
    only_5xx = []
    for inst in item_instructions:
        num = str((inst or {}).get("number") or "")
        prefix = num.split(".")[0] if "." in num else num
        if prefix in {"501", "502", "503", "504"}:
            only_5xx.append(inst)
        else:
            non_5xx.append(inst)

    non_5xx = _unique_by_number(non_5xx)
    only_5xx = _unique_by_number(only_5xx)

    all_instructions.extend(non_5xx)
    all_instructions.extend(only_5xx)

    # Deterministic 500-series from claim mapping (union across case)
    try:
        logger.info(
            "5xx-selection: starting; claims=%s counterclaims=%s",
            [c.get("claim_id") for c in (claims or [])],
            [c.get("claim_id") for c in (counterclaims or [])],
        )
        selected_numbers: set[str] = set()

        def _accumulate(items: list[dict]):
            for info in items or []:
                cid = (info or {}).get("claim_id")
                if not cid:
                    logger.info("5xx-selection: skipping item without claim_id: %s", info)
                    continue
                db_claim = instruction_processing.database_get_claim_by_id(cid) or {}
                mapping = (db_claim.get("damages") or {}) if isinstance(db_claim, dict) else {}
                cat = ((mapping.get("claim_category") or db_claim.get("claim_category") or "").lower()
                       if isinstance(db_claim, dict) else "")
                logger.info(
                    "5xx-selection: claim_id=%s mapping_keys=%s",
                    cid,
                    list(mapping.keys()) if isinstance(mapping, dict) else type(mapping).__name__,
                )
                for n in mapping.get("damages_instructions") or []:
                    if not n:
                        continue
                    n_str = str(n)
                    # Filter out personal injury 501.x when claim category is not injury-related
                    if n_str.startswith("501") and not any(w in cat for w in ("injury", "medical")):
                        logger.info("5xx-selection: skipping %s for non-injury category=%s", n_str, cat)
                        continue
                    if n_str.startswith("502") and not any(w in cat for w in ("injury", "medical")):
                        logger.info("5xx-selection: skipping %s for non-injury category=%s", n_str, cat)
                        continue
                        selected_numbers.add(str(n))
                        logger.info("5xx-selection: added from mapping claim_id=%s number=%s", cid, n)
                if mapping.get("allows_punitive") and bool((info.get("damages") or {}).get("seeks_punitive")):
                    selected_numbers.add("503.1")
                    logger.info("5xx-selection: added punitive 503.1 for claim_id=%s", cid)

        _accumulate(claims)
        _accumulate(counterclaims)

        logger.info("5xx-selection: final set=%s", sorted(selected_numbers))
        for num in sorted(selected_numbers):
            inst = instruction_processing._get_instruction_by_number(str(num))
            if not inst:
                logger.warning("5xx-selection: template not found for number=%s", num)
                continue
            text = instruction_processing._llm_render_instruction(
                template_text=inst.get("main_paragraph", ""), inputs={}
            )
            if text:
                logger.info("5xx-selection: rendered number=%s length=%s", num, len(text))
                all_instructions.append({
                    "number": inst.get("number"),
                    "title": inst.get("title"),
                    "customized_text": text,
                })
            else:
                logger.warning("5xx-selection: render failed for number=%s", num)
    except Exception:
        # Do not fail the whole job if damages phase fails
        pass

    # 600 series
    try:
        s601_1 = instruction_processing._generate_601_1()
        if s601_1:
            all_instructions.append(s601_1)
    except Exception:
        pass

    try:
        s601_2 = instruction_processing._generate_601_2(config=config)
        if s601_2:
            all_instructions.append(s601_2)
    except Exception:
        pass

    try:
        s601_3 = instruction_processing._generate_601_3(config=config)
        if s601_3:
            all_instructions.append(s601_3)
    except Exception:
        pass

    try:
        s601_4 = instruction_processing._generate_601_4(claims=claims, counterclaims=counterclaims)
        if s601_4:
            all_instructions.append(s601_4)
    except Exception:
        pass

    try:
        s601_5 = instruction_processing._generate_601_5(config=config)
        if s601_5:
            all_instructions.append(s601_5)
    except Exception:
        pass

    verdict_form = _generate_verdict_form(
        claims=claims,
        counterclaims=counterclaims,
        case_facts=case_facts,
        config=config
    )

    # Return combined object to allow downstream to access verdict_form while preserving
    # backward-compatibility (SaveResults will handle both shapes).
    # Final de-duplication by instruction number, preserving first occurrence order
    seen_nums: set[str] = set()
    deduped: list[dict] = []
    for inst in all_instructions:
        num = (inst or {}).get("number")
        if not num or num not in seen_nums:
            deduped.append(inst)
            if num:
                seen_nums.add(num)

    return {"instructions": deduped, "verdict_form": verdict_form}
