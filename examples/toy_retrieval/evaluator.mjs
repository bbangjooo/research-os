#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const workspace = path.resolve(process.argv[2]);
const project = path.dirname(fileURLToPath(import.meta.url));
const policy = JSON.parse(fs.readFileSync(path.join(workspace, "retrieval.json"), "utf8"));
const corpus = JSON.parse(fs.readFileSync(path.join(project, "data", "corpus.json"), "utf8"));
const queries = JSON.parse(fs.readFileSync(path.join(project, "data", "queries.json"), "utf8"));

const tokens = (value) => new Set(value.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean));
let hits = 0;
for (const query of queries) {
  const q = tokens(query.text);
  const ranked = corpus.map((doc) => {
    const title = tokens(doc.title);
    const body = tokens(doc.body);
    const titleHits = [...q].filter((x) => title.has(x)).length;
    const bodyHits = [...q].filter((x) => body.has(x)).length;
    return { id: doc.id, score: titleHits * policy.title_weight + bodyHits * policy.body_weight };
  }).sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
  if (ranked[0].id === query.target_id) hits += 1;
}
const out = path.join(workspace, "outputs");
fs.mkdirSync(out, { recursive: true });
fs.writeFileSync(path.join(out, "result.json"), JSON.stringify({
  metrics: { recall_at_1: hits / queries.length, documents_scored: corpus.length * queries.length },
  constraints: [],
  resource_usage: { queries: queries.length },
}) + "\n");
