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
            out.append(inst)
    return out


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
                logger.info(
                    "5xx-selection: claim_id=%s mapping_keys=%s",
                    cid,
                    list(mapping.keys()) if isinstance(mapping, dict) else type(mapping).__name__,
                )
                for n in mapping.get("damages_instructions") or []:
                    if n:
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

    return all_instructions
