import contextlib
import json
import os
from pathlib import Path
import sys

import streamlit as st

EXAMPLES = ["one", "two"]
LAMBDA_DIR_MAP: dict[str, str] = {
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
                if len(parts) > 3 and parts[2] == "lambda":  # noqa: PLR2004
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


def resolve_handler(lambda_name: str) -> tuple[callable, Path]:
    lambda_subdir = LAMBDA_DIR_MAP[lambda_name]
    lambda_dir = Path("lambdas") / lambda_subdir
    if not lambda_dir.exists():
        raise FileNotFoundError(f"Lambda directory not found: {lambda_dir}")
    lambda_path = str(lambda_dir.resolve())
    if lambda_path not in sys.path:
        sys.path.insert(0, lambda_path)
    # Dev hot-reload: drop any previously loaded modules from this lambda folder
    try:
        lambda_root = lambda_dir.resolve()
        to_delete = []
        for name, mod in list(sys.modules.items()):
            f = getattr(mod, "__file__", None)
            if not f:
                continue
            try:
                p = Path(f).resolve()
                if str(p).startswith(str(lambda_root)):
                    to_delete.append(name)
            except Exception:
                continue
        for name in to_delete:
            sys.modules.pop(name, None)
    except Exception:
        pass
    try:
        from importlib.util import module_from_spec, spec_from_file_location

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
        ) from e
    if not hasattr(module, "lambda_handler"):
        raise AttributeError(f"main.py in {lambda_dir} does not expose lambda_handler")
    return module.lambda_handler, lambda_dir


@st.cache_data
def list_inputs(example: str, lambda_name: str) -> list[Path]:
    inputs_dir = Path("examples") / example / "inputs"
    return sorted(inputs_dir.glob(f"{lambda_name}-*.json"))


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def run_single(lambda_name: str, payload):
    handler, _ = resolve_handler(lambda_name)
    return handler(payload, None)


def run_with_logs(lambda_name: str, payload):
    """Run the lambda and capture logs/stdio output. Returns (result, logs_text)."""
    from contextlib import redirect_stderr, redirect_stdout
    from io import StringIO
    import logging

    handler, _ = resolve_handler(lambda_name)

    log_buf = StringIO()
    out_buf = StringIO()
    err_buf = StringIO()

    root_logger = logging.getLogger()
    stream_handler = logging.StreamHandler(log_buf)
    stream_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    try:
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            result = handler(payload, None)
    finally:
        root_logger.removeHandler(stream_handler)

    logs = log_buf.getvalue()
    if out_buf.getvalue():
        logs += "\n[stdout]\n" + out_buf.getvalue()
    if err_buf.getvalue():
        logs += "\n[stderr]\n" + err_buf.getvalue()

    return result, logs


def run_with_live_logs(lambda_name: str, payload, log_placeholder, logs_key: str):
    """Run the lambda in a background thread and stream logs/stdout/stderr
    into the provided Streamlit placeholder in near real time.

    Returns the handler result (or raises the handler's exception).
    """
    from contextlib import redirect_stderr, redirect_stdout
    import logging
    import queue
    import threading
    import time

    handler, _ = resolve_handler(lambda_name)

    q: queue.Queue[str] = queue.Queue()

    class QueueWriter:
        def write(self, s):
            if s:
                q.put(s)
        def flush(self):
            pass

    # Logging handler that feeds the queue
    root_logger = logging.getLogger()
    stream_handler = logging.StreamHandler(QueueWriter())
    stream_handler.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stream_handler.setFormatter(formatter)

    result_holder = {"result": None, "error": None}

    def target():
        root_logger.addHandler(stream_handler)
        try:
            with redirect_stdout(QueueWriter()), redirect_stderr(QueueWriter()):
                result_holder["result"] = handler(payload, None)
        except Exception as e:
            result_holder["error"] = e
        finally:
            with contextlib.suppress(Exception):
                root_logger.removeHandler(stream_handler)

    t = threading.Thread(target=target, daemon=True)
    t.start()

    log_buffer = ""
    # Stream until thread finishes and queue is drained
    while t.is_alive() or not q.empty():
        try:
            while True:
                chunk = q.get_nowait()
                log_buffer += chunk
        except queue.Empty:
            pass
        # Update UI with a stable key per run
        # Update UI without widget state conflicts
        log_placeholder.code(log_buffer or "(no logs yet)")
        time.sleep(0.15)

    # Final drain
    try:
        while True:
            chunk = q.get_nowait()
            log_buffer += chunk
    except queue.Empty:
        pass
    log_placeholder.code(log_buffer or "(no logs)")

    if result_holder["error"] is not None:
        raise result_holder["error"]
    return result_holder["result"]


def main():  # noqa: PLR0912, PLR0915
    st.set_page_config(page_title="Jury Gen – Local Runner", layout="wide")  # noqa: RUF001
    # Hide Streamlit chrome (deploy/toolbar/menu)
    st.markdown(
        """
        <style>
        [data-testid="stDeployButton"] {display: none !important;}
        [data-testid="stToolbar"] {visibility: hidden !important; height: 0;}
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("Jury Gen – Local Lambda Runner")  # noqa: RUF001

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
                with st.expander(f"{i:03d} – {path.name}", expanded=False):  # noqa: RUF001
                    st.write("Input")
                    payload = load_json(path)
                    st.json(payload)
                    try:
                        log_box = st.empty()
                        st.caption(f"Running {lambda_name} on {path.name}...")
                        result = run_with_live_logs(lambda_name, payload, log_box, logs_key=f"logs-{lambda_name}-{i}")
                        st.write("Output")
                        if isinstance(result, str):
                            st.text_area(
                                "Output (text)", result, height=400, disabled=True, key=f"out-{lambda_name}-{i}"
                            )
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
                    log_box = st.empty()
                    status = st.empty()
                    status.info("Running Lambda...")
                    result = run_with_live_logs(
                        lambda_name, payload, log_box, logs_key=f"logs-{lambda_name}-{selected.name}"
                    )
                    status.success("Run completed")
                    st.success("Run completed")
                    if isinstance(result, str):
                        st.text_area(
                            "Output (text)", result, height=400, disabled=True, key=f"out-{lambda_name}-{selected.name}"
                        )
                    else:
                        st.json(result)
                except Exception as e:
                    st.error(str(e))


if __name__ == "__main__":
    main()
