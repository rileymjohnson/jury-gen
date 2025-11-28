#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import importlib
from pathlib import Path
from typing import Dict, List, Tuple

import streamlit as st


EXAMPLES = ["one", "two"]
LAMBDA_DIR_MAP: Dict[str, str] = {
    "enrich_legal_item": "enrich_legal_item",
    "extract_case_facts": "extract_case_facts",
    "extract_legal_claims": "extract_legal_claims",
    "extract_witnesses": "extract_witnesses",
    "generate_instructions": "generate_instructions",
}


def infer_region_from_history(example: str) -> str | None:
    history = Path("examples") / example / "sfn_events.json"
    if not history.exists():
        return None
    try:
        data = json.loads(history.read_text(encoding="utf-8"))
        for ev in data:
            if ev.get("type") == "LambdaFunctionScheduled":
                arn = (ev.get("lambdaFunctionScheduledEventDetails") or {}).get("resource") or ""
                parts = arn.split(":")
                if len(parts) > 3 and parts[2] == "lambda":
                    return parts[3]
    except Exception:
        return None
    return None


def ensure_region(region: str | None, example: str) -> str | None:
    region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if not region:
        region = infer_region_from_history(example) or region
    if region:
        os.environ.setdefault("AWS_REGION", region)
        os.environ.setdefault("AWS_DEFAULT_REGION", region)
    return region


def resolve_handler(lambda_name: str) -> Tuple[callable, Path]:
    lambda_subdir = LAMBDA_DIR_MAP[lambda_name]
    lambda_dir = Path("lambdas") / lambda_subdir
    if not lambda_dir.exists():
        raise FileNotFoundError(f"Lambda directory not found: {lambda_dir}")
    lambda_path = str(lambda_dir.resolve())
    if lambda_path not in sys.path:
        sys.path.insert(0, lambda_path)
    try:
        from importlib.util import spec_from_file_location, module_from_spec

        main_py = lambda_dir / "main.py"
        module_name = f"lambda_{lambda_name}_main"
        spec = spec_from_file_location(module_name, main_py)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load {main_py}")
        module = module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except ModuleNotFoundError as e:
        missing = getattr(e, "name", str(e))
        raise RuntimeError(
            f"Failed to import Lambda module dependencies. Missing: {missing}. "
            "Install deps (e.g. boto3) or activate your venv."
        )
    if not hasattr(module, "lambda_handler"):
        raise AttributeError(f"main.py in {lambda_dir} does not expose lambda_handler")
    return module.lambda_handler, lambda_dir


@st.cache_data
def list_inputs(example: str, lambda_name: str) -> List[Path]:
    inputs_dir = Path("examples") / example / "inputs"
    return sorted(inputs_dir.glob(f"{lambda_name}-*.json"))


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def run_single(lambda_name: str, payload):
    handler, _ = resolve_handler(lambda_name)
    return handler(payload, None)


def main():
    st.set_page_config(page_title="Jury Gen – Local Runner", layout="wide")
    st.title("Jury Gen – Local Lambda Runner")

    with st.sidebar:
        st.header("Controls")
        example = st.selectbox("Example", EXAMPLES, index=0)
        lambda_name = st.selectbox("Lambda", sorted(LAMBDA_DIR_MAP.keys()), index=0)

        # Region is auto-inferred from history; no manual selection
        st.divider()

    files = list_inputs(example, lambda_name)
    if not files:
        st.warning(
            f"No inputs found for {lambda_name} under examples/{example}/inputs. "
            "Run scripts/extract_lambda_inputs.py first."
        )
        return

    st.subheader("Available Inputs")
    st.caption(f"Found {len(files)} input file(s)")

    # Selection: "All" or a specific file by name
    options = ["All"] + [p.name for p in files]
    choice = st.selectbox("Run which input?", options, index=0)

    if choice == "All":
        if st.button("Run All", type="primary"):
            ensure_region(None, example)
            if lambda_name == "extract_legal_claims":
                os.environ.setdefault("DYNAMODB_CLAIMS_TABLE_NAME", "Claims-dev")
            if lambda_name == "generate_instructions":
                os.environ.setdefault("DYNAMODB_CLAIMS_TABLE_NAME", "Claims-dev")
                os.environ.setdefault(
                    "DYNAMODB_STANDARD_JURY_INSTRUCTIONS_TABLE_NAME", "StandardJuryInstructions-dev"
                )
            progress = st.progress(0, text="Running all inputs...")
            total = len(files)
            for i, path in enumerate(files, start=1):
                with st.expander(f"{i:03d} – {path.name}", expanded=False):
                    st.write("Input")
                    payload = load_json(path)
                    st.json(payload)
                    try:
                        with st.spinner(f"Running {lambda_name} on {path.name}..."):
                            result = run_single(lambda_name, payload)
                        st.write("Output")
                        if isinstance(result, str):
                            st.text_area("Output (text)", result, height=400, disabled=True)
                        else:
                            st.json(result)
                    except Exception as e:
                        st.error(str(e))
                progress.progress(i / total, text=f"Processed {i}/{total}")
            progress.empty()
    else:
        # Specific file selected
        selected = next(p for p in files if p.name == choice)
        col1, col2 = st.columns(2)
        with col1:
            st.write("Input file:", selected.name)
            st.json(load_json(selected))
        with col2:
            if st.button("Run Selected", type="primary"):
                ensure_region(None, example)
                if lambda_name == "extract_legal_claims":
                    os.environ.setdefault("DYNAMODB_CLAIMS_TABLE_NAME", "Claims-dev")
                if lambda_name == "generate_instructions":
                    os.environ.setdefault("DYNAMODB_CLAIMS_TABLE_NAME", "Claims-dev")
                    os.environ.setdefault(
                        "DYNAMODB_STANDARD_JURY_INSTRUCTIONS_TABLE_NAME", "StandardJuryInstructions-dev"
                    )
                payload = load_json(selected)
                try:
                    with st.spinner("Running Lambda... this may take a moment"):
                        result = run_single(lambda_name, payload)
                    st.success("Run completed")
                    if isinstance(result, str):
                        st.text_area("Output (text)", result, height=400, disabled=True)
                    else:
                        st.json(result)
                except Exception as e:
                    st.error(str(e))


if __name__ == "__main__":
    main()
