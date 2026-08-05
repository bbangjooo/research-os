#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { spawnSync } from "node:child_process";

const VERSION = 1;
const operations = new Set(["describe", "fingerprint", "baseline", "materialize", "run", "evaluate", "verify", "cleanup"]);
const request = JSON.parse(fs.readFileSync(0, "utf8"));

function respond(ok, payload = {}, error = undefined) {
  const response = {
    protocol_version: VERSION,
    request_id: request.request_id,
    ok,
    retryable: false,
    payload,
    diagnostics: [],
  };
  if (error) response.error = error;
  process.stdout.write(JSON.stringify(response));
}

try {
  if (request.protocol_version !== VERSION || !operations.has(request.operation)) {
    throw new Error("unsupported protocol or operation");
  }
  const project = path.resolve(request.project_root);
  const workspace = path.resolve(request.workspace || project);
  const resultPath = path.join(workspace, "outputs", "result.json");

  if (request.operation === "describe") {
    respond(true, { capabilities: [...operations].sort(), side_effects: [] });
  } else if (request.operation === "fingerprint") {
    respond(true, { dataset: "tiny-corpus-v1", evaluator: "token-overlap-v1" });
  } else if (request.operation === "materialize") {
    const candidate = request.payload?.candidate || {};
    if (!Number.isFinite(candidate.title_weight) || candidate.title_weight < 0) {
      respond(false, {}, { category: "INVALID_EXPERIMENT", code: "INVALID_CANDIDATE", message: "title_weight must be non-negative" });
    } else {
      const current = JSON.parse(fs.readFileSync(path.join(workspace, "retrieval.json"), "utf8"));
      current.title_weight = candidate.title_weight;
      fs.writeFileSync(path.join(workspace, "retrieval.json"), JSON.stringify(current) + "\n");
      respond(true);
    }
  } else if (request.operation === "baseline" || request.operation === "run") {
    const completed = spawnSync(process.execPath, [path.join(project, "evaluator.mjs"), workspace], { encoding: "utf8" });
    if (completed.status !== 0) {
      respond(false, {}, { category: "INFRASTRUCTURE", code: "EVALUATOR_FAILED", message: (completed.stderr || "").slice(-1000) });
    } else {
      if (request.operation === "baseline") {
        const result = JSON.parse(fs.readFileSync(resultPath, "utf8"));
        result.artifacts = [{ path: "outputs/result.json", media_type: "application/json", retention: "run", sensitivity: "public" }];
        respond(true, result);
      } else {
        respond(true);
      }
    }
  } else if (request.operation === "evaluate") {
    const result = JSON.parse(fs.readFileSync(resultPath, "utf8"));
    result.artifacts = [{ path: "outputs/result.json", media_type: "application/json", retention: "project", sensitivity: "public" }];
    respond(true, result);
  } else if (request.operation === "verify") {
    const result = JSON.parse(fs.readFileSync(resultPath, "utf8"));
    const valid = Number.isFinite(result.metrics?.recall_at_1);
    const verdict = { valid, reason_code: valid ? "OK" : "MISSING_RECALL" };
    if (!valid) verdict.category = "INSUFFICIENT_EVIDENCE";
    respond(true, verdict);
  } else {
    respond(true);
  }
} catch (error) {
  respond(false, {}, { category: "INFRASTRUCTURE", code: "ADAPTER_EXCEPTION", message: String(error.message || error) });
}
