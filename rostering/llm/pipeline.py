"""Direct generation, optional bounded model critique, then independent evaluation."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

from .api import APIError, completed, output_text, request_response, response_status, token_usage
from ..contracts import ROOT, validate_instance
from ..evaluate import evaluate
from ..io import write_json
from .safeguards import CRITIQUE_INSTRUCTIONS, REVISION_INSTRUCTIONS, VARIANTS, attach_schema, roster_generation_schema, text_request


def build_request(instance: dict, config: dict, max_output_tokens: int, variant: str = "baseline") -> tuple[str, dict]:
    if variant not in VARIANTS:
        raise ValueError("Unknown experimental variant")
    validate_instance(instance)
    prompt = (ROOT / "prompts" / "baseline.txt").read_text() + "\n" + json.dumps(instance, ensure_ascii=False)
    payload = text_request(config, prompt, max_output_tokens)
    if variant in {"structured", "combined"}:
        attach_schema(payload, roster_generation_schema(instance), config["api_style"])
    return prompt, payload


def revision() -> dict:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True))
        return {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def run_roster(instance: dict, config: dict, output_root: Path, *, max_output_tokens: int = 32000, audit_output_tokens: int = 16000, timeout: float | None = None, dry_run: bool = False, variant: str = "baseline", total_timeout: float | None = None) -> tuple[Path, dict]:
    if max_output_tokens < 1 or audit_output_tokens < 1:
        raise ValueError("Token limits must be positive")
    if timeout is not None and not 0 < timeout < float("inf"):
        raise ValueError("Request timeout must be finite and positive")
    if total_timeout is not None and not 0 < total_timeout < float("inf"):
        raise ValueError("Total timeout must be finite and positive")
    trial_started = time.perf_counter()
    prompt, payload = build_request(instance, config, max_output_tokens, variant)
    started = datetime.now(timezone.utc)
    # Random suffix avoids overwriting results from concurrent or repeated runs.
    directory = output_root / (started.strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "instance.json", instance)
    write_json(directory / "request.json", payload)
    (directory / "prompt.txt").write_text(prompt)
    (directory / "uv.lock").write_text((ROOT / "uv.lock").read_text())
    metadata = {
        "run_id": directory.name, "instance_id": instance["instance_id"],
        "variant": variant, "prompt_version": "hard_only_v1",
        "mode": "hard_constraints_only", "soft_method": None,
        "objective_scope": "Feasibility only; no soft objective",
        "started_at_utc": started.isoformat(), "status": "dry_run" if dry_run else "started",
        "requested_model": config["model"], "provider": config["provider"],
        "base_url": config["base_url"], "api_style": config["api_style"],
        "request_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        "timeout_seconds": timeout, "max_output_tokens": max_output_tokens,
        "audit_output_tokens": audit_output_tokens,
        "total_timeout_seconds": total_timeout, "runtime_seconds": None,
        "decoding": {"temperature": "provider_default", "seed": "not_requested", "reasoning": config.get("reasoning_effort", "provider_default")},
        "python_version": sys.version.split()[0],
        "source_sha256": {
            path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for pattern in ["rostering/**/*.py", "schemas/*.json", "prompts/*.txt"]
            for path in sorted(ROOT.glob(pattern))
        },
        "git": revision(), "latency_seconds": None, "usage": None,
        "returned_model": None, "cost": None, "cost_note": "No verified provider tariff configured",
        "stages": [], "api_call_count": 0,
    }
    write_json(directory / "metadata.json", metadata)
    if dry_run:
        return directory, metadata
    def call_stage(name: str, request: dict) -> dict:
        stage_timeout = timeout
        if total_timeout is not None:
            remaining = total_timeout - (time.perf_counter() - trial_started)
            if remaining <= 0:
                raise APIError("Total trial time budget exhausted before " + name)
            stage_timeout = remaining if timeout is None else min(timeout, remaining)
        stage_dir = directory / "stages" / name
        write_json(stage_dir / "request.json", request)
        metadata["api_call_count"] += 1
        write_json(directory / "metadata.json", metadata)
        call_started = time.perf_counter()
        try:
            response, latency = request_response(config, request, stage_timeout)
        except APIError:
            metadata["stages"].append({"name": name, "latency_seconds": time.perf_counter() - call_started, "usage": {}, "response_status": "api_error", "returned_model": None, "usage_missing": True})
            write_json(directory / "metadata.json", metadata)
            raise
        write_json(stage_dir / "response.json", response)
        (stage_dir / "output.txt").write_text(output_text(response))
        metadata["stages"].append({"name": name, "latency_seconds": latency, "usage": token_usage(response), "response_status": response_status(response), "returned_model": response.get("model")})
        write_json(directory / "metadata.json", metadata)
        return response

    try:
        response = call_stage("generation", payload)
        if variant in {"critique", "combined"}:
            if completed(response) and output_text(response).strip():
                candidate = output_text(response)
                audit_prompt = CRITIQUE_INSTRUCTIONS + "\nINSTANCE:\n" + json.dumps(instance) + "\nCANDIDATE:\n" + candidate
                audit = call_stage("critique", text_request(config, audit_prompt, audit_output_tokens))
                if completed(audit) and output_text(audit).strip():
                    revision_prompt = prompt + "\n" + REVISION_INSTRUCTIONS + "\nCANDIDATE:\n" + candidate + "\nLLM AUDIT:\n" + output_text(audit)
                    revision_payload = text_request(config, revision_prompt, max_output_tokens)
                    if variant == "combined":
                        attach_schema(revision_payload, roster_generation_schema(instance), config["api_style"])
                    response = call_stage("revision", revision_payload)
                else:
                    metadata["critique_incomplete"] = True
            else:
                metadata["critique_skipped"] = "Generation was incomplete or empty"
    except APIError as error:
        metadata.update(
            status="api_error", error=str(error), finished_at_utc=datetime.now(timezone.utc).isoformat(),
            latency_seconds=sum(stage["latency_seconds"] for stage in metadata["stages"]),
            usage=({key: sum(stage["usage"].get(key, 0) for stage in metadata["stages"]) for key in ["input_tokens", "output_tokens", "total_tokens"]} if any(stage["usage"] for stage in metadata["stages"]) else None),
            usage_incomplete=True,
            runtime_seconds=time.perf_counter() - trial_started,
        )
        write_json(directory / "metadata.json", metadata)
        raise APIError(f"{error}. Run artifacts: {directory}") from None
    write_json(directory / "response.json", response)
    text = output_text(response)
    (directory / "response.txt").write_text(text)
    metadata.update(
        returned_model=response.get("model"), response_id=response.get("id"),
        response_status=response_status(response), incomplete_details=response.get("incomplete_details"),
        latency_seconds=sum(stage["latency_seconds"] for stage in metadata["stages"]),
        usage={key: sum(stage["usage"].get(key, 0) for stage in metadata["stages"]) for key in ["input_tokens", "output_tokens", "total_tokens"]},
        # Preserve reported decoding settings without assuming the gateway honours them.
        reported_settings={k: response[k] for k in ["temperature", "top_p", "reasoning", "service_tier"] if k in response},
        finished_at_utc=datetime.now(timezone.utc).isoformat(),
    )
    metadata["output_cap_reached"] = token_usage(response).get("output_tokens", 0) >= max_output_tokens
    try:
        result = json.loads(text)
    except ValueError:
        report = evaluate(instance, None)
        report["parse_error"] = "Response is not a standalone JSON value; no repair was attempted"
        metadata["status"] = "invalid_json" if text.strip() else "empty_response"
    else:
        write_json(directory / "roster.json", result)
        report = evaluate(instance, result)
        metadata["status"] = "valid_roster" if report["hard_valid"] else "invalid_roster"
        if report["schema_valid"] and report["solution_status"] != "candidate":
            metadata["status"] = report["solution_status"]
    if not completed(response):
        metadata["status"] = "incomplete_response"
        report.update(evaluation_status="incomplete_response", hard_valid=False, soft_score=None)
    write_json(directory / "evaluation.json", report)
    # Score the original candidate only after all model calls; never feed this back.
    generation_text = (directory / "stages/generation/output.txt").read_text()
    try:
        generation_result = json.loads(generation_text)
    except ValueError:
        generation_result = None
    generation_report = evaluate(instance, generation_result)
    if metadata["stages"][0]["response_status"] not in {"completed", "stop"}:
        generation_report.update(evaluation_status="incomplete_response", hard_valid=False, soft_score=None)
    write_json(directory / "stages/generation/evaluation.json", generation_report)
    metadata["runtime_seconds"] = time.perf_counter() - trial_started
    write_json(directory / "metadata.json", metadata)
    return directory, metadata
