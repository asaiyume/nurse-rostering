"""Check observed schema behaviour on both gateway APIs; no credentials are saved."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from jsonschema import Draft202012Validator

from .api import APIError, completed, output_text, request_response, token_usage
from ..contracts import ROOT
from ..io import write_json
from .safeguards import attach_schema, text_request


def probe_style(config: dict, style: str, directory: Path) -> dict:
    config = {**config, "api_style": style}
    sentinel = "SCHEMA_" + uuid.uuid4().hex
    schema = {
        "type": "object", "properties": {"proof": {"type": "string", "enum": [sentinel]}},
        "required": ["proof"], "additionalProperties": False,
    }
    results = {}
    for kind in ["valid_schema", "invalid_schema"]:
        target = schema if kind == "valid_schema" else {"type": "object", "properties": {}, "required": ["missing_property"], "additionalProperties": False}
        payload = text_request(config, "Return exactly the word UNSTRUCTURED as plain text. Do not output JSON.", 512)
        attach_schema(payload, target, style)
        write_json(directory / f"{style}_{kind}_request.json", payload)
        try:
            response, latency = request_response(config, payload, timeout=60)
        except APIError as error:
            results[kind] = {"accepted": False, "error": str(error)}
            continue
        write_json(directory / f"{style}_{kind}_response.json", response)
        text = output_text(response)
        conforms = False
        try:
            parsed = json.loads(text)
            conforms = not list(Draft202012Validator(schema).iter_errors(parsed))
        except ValueError:
            pass
        results[kind] = {"accepted": True, "completed": completed(response), "conforms_to_valid_schema": conforms, "text": text, "latency_seconds": latency, "usage": token_usage(response)}
    positive = results["valid_schema"]
    negative = results["invalid_schema"]
    results["structured_output_observed"] = bool(positive.get("completed") and positive.get("conforms_to_valid_schema"))
    results["invalid_schema_rejected_400"] = "HTTP 400" in negative.get("error", "")
    results["assessment"] = (
        "observed_schema_conformance_and_invalid_schema_rejection"
        if results["structured_output_observed"] and results["invalid_schema_rejected_400"]
        else "strict_enforcement_not_established"
    )
    return results


def main() -> None:
    config = json.loads((ROOT / "config/llm.json").read_text())
    directory = ROOT / "outputs" / ("schema_probe_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {style: pool.submit(probe_style, config, style, directory) for style in ["responses", "chat_completions"]}
        result = {style: future.result() for style, future in futures.items()}
    write_json(directory / "summary.json", result)
    print(json.dumps({"directory": str(directory), "results": result}, indent=2))


if __name__ == "__main__":
    main()
