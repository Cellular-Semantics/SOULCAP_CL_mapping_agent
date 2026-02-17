"""
Audit SOULCAP marker definitions against Protein Ontology terms using the
OLS4 API, surfacing mismatches and suggested replacements.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

import requests

OLS4_BASE = "https://www.ebi.ac.uk/ols4/api"
PR_ONTOLOGY = "pr"
TERM_TEMPLATE = f"{OLS4_BASE}/ontologies/{PR_ONTOLOGY}/terms/{{encoded_iri}}"
SEARCH_ENDPOINT = f"{OLS4_BASE}/search"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pbmc-json",
        type=Path,
        default=Path("resources/pbmc_jsonld_cl.json"),
        help="PBMC SOULCAP JSON-LD file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("resources/pr_mapping_audit_ols.tsv"),
        help="TSV path for the audit report",
    )
    parser.add_argument(
        "--max-suggestions",
        type=int,
        default=5,
        help="Number of alternative PR suggestions to capture per mismatch",
    )
    return parser.parse_args()


def load_marker_definitions(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    definitions: list[dict] = []
    for raw_pr, meta in data.get("marker_definitions", {}).items():
        pr_curie = normalize_pr_curie(raw_pr)
        if not pr_curie:
            continue
        definitions.append(
            {
                "pr": pr_curie,
                "symbol": meta.get("symbol"),
                "name": meta.get("name"),
            }
        )
    return definitions


def normalize_pr_curie(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if value.lower().startswith("pr:"):
        return f"pr:{value.split(':', 1)[1].zfill(7)}"
    if value.startswith("obo:PR_"):
        return f"pr:{value.split('PR_', 1)[1].zfill(7)}"
    if value.startswith("http://purl.obolibrary.org/obo/PR_"):
        return f"pr:{value.rsplit('_', 1)[1].zfill(7)}"
    return None


def to_pr_iri(pr_curie: str) -> str:
    local = pr_curie.split(":", 1)[1]
    return f"http://purl.obolibrary.org/obo/PR_{local.zfill(7)}"


def fetch_pr_entry(pr_curie: str) -> dict | None:
    iri = to_pr_iri(pr_curie)
    encoded = quote(quote(iri, safe=""), safe="")
    url = TERM_TEMPLATE.format(encoded_iri=encoded)
    response = requests.get(url, timeout=60)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    data = response.json()
    synonyms = set(filter(None, data.get("synonyms", [])))
    for syn in data.get("obo_synonym") or []:
        name = syn.get("name")
        if name:
            synonyms.add(name)
    normalized = {
        "iri": data.get("iri"),
        "label": data.get("label"),
        "synonyms": sorted(synonyms),
    }
    return normalized


def normalize_token(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"\s+", " ", value.strip()).lower()


def has_match(value: str | None, entry: dict | None) -> bool:
    token = normalize_token(value)
    if not token or not entry:
        return False
    candidates = {normalize_token(entry.get("label"))}
    candidates |= {normalize_token(syn) for syn in entry.get("synonyms", [])}
    candidates.discard(None)
    return token in candidates


def build_query_terms(value: str) -> list[str]:
    terms: list[str] = []
    base = value.strip()
    if base:
        terms.append(base)
    clean = re.sub(r"[/-]", " ", base)
    tokens = clean.split()
    if len(tokens) > 1:
        terms.append(tokens[0])
    cd_match = re.match(r"cd\s*([0-9]+)([a-z]*)", base, re.IGNORECASE)
    if cd_match:
        cd_base = f"CD{cd_match.group(1)}{cd_match.group(2).upper()}"
        terms.extend(
            [
                cd_base,
                f"{cd_base} protein",
                f"{cd_base} antigen",
                f"{cd_base} molecule",
            ]
        )
    return [t for i, t in enumerate(terms) if t and t not in terms[:i]]


def search_pr(value: str, max_hits: int) -> list[dict]:
    suggestions: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for query in build_query_terms(value):
        params = {
            "q": query,
            "ontology": PR_ONTOLOGY,
            "rows": max_hits,
        }
        response = requests.get(SEARCH_ENDPOINT, params=params, timeout=60)
        response.raise_for_status()
        docs = response.json().get("response", {}).get("docs", [])
        for doc in docs:
            pr_id = doc.get("obo_id") or doc.get("short_form")
            label = doc.get("label")
            if not pr_id or not label:
                continue
            key = (pr_id, label)
            if key in seen:
                continue
            seen.add(key)
            suggestions.append({"id": pr_id, "label": label, "query": query})
            if len(suggestions) >= max_hits:
                return suggestions
    return suggestions


def audit_definitions(definitions: list[dict], max_suggestions: int) -> list[dict]:
    rows: list[dict] = []
    for definition in definitions:
        pr_curie = definition["pr"]
        entry = fetch_pr_entry(pr_curie)
        for field in ("symbol", "name"):
            value = definition.get(field)
            if not value:
                continue
            matched = has_match(value, entry)
            suggestions = []
            if not matched:
                suggestions = search_pr(value, max_suggestions)
            rows.append(
                {
                    "pr_id": pr_curie,
                    "field": field,
                    "soulcap_value": value,
                    "status": "matched" if matched else "unmatched",
                    "pr_label": entry.get("label") if entry else "-",
                    "pr_synonyms": "; ".join(entry.get("synonyms", []))
                    if entry
                    else "-",
                    "suggestions": "; ".join(
                        f"{item['id']} ({item['label']}) [q={item['query']}]"
                        for item in suggestions
                    )
                    if suggestions
                    else "-",
                }
            )
        if entry is None:
            rows.append(
                {
                    "pr_id": pr_curie,
                    "field": "term_lookup",
                    "soulcap_value": "-",
                    "status": "missing",
                    "pr_label": "-",
                    "pr_synonyms": "-",
                    "suggestions": "-",
                }
            )
    return rows


def write_report(rows: list[dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "pr_id",
                "field",
                "soulcap_value",
                "status",
                "pr_label",
                "pr_synonyms",
                "suggestions",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    definitions = load_marker_definitions(args.pbmc_json)
    if not definitions:
        raise SystemExit("No marker definitions found.")
    rows = audit_definitions(definitions, args.max_suggestions)
    write_report(rows, args.output)
    unmatched = sum(1 for row in rows if row["status"] != "matched")
    print(
        f"Wrote {len(rows)} audit rows to {args.output}; "
        f"{unmatched} entries require review."
    )


if __name__ == "__main__":
    main()
