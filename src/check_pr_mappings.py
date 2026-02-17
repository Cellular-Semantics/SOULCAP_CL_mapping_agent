"""
Audit PBMC marker PR mappings by comparing SOULCAP marker names/symbols
against PR labels and synonyms from UberGraph, suggesting replacements
when mismatches are detected.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable, TypeVar

import requests

UBERGRAPH_ENDPOINT = "https://ubergraph.apps.renci.org/sparql"
PR_ONTOLOGY_IRI = "http://purl.obolibrary.org/obo/pr.owl"
PR_PREFIX = "http://purl.obolibrary.org/obo/PR_"
SYNONYM_PROPS = [
    "http://www.geneontology.org/formats/oboInOwl#hasExactSynonym",
    "http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pbmc-json",
        type=Path,
        default=Path("resources/pbmc_jsonld_cl.json"),
        help="PBMC SOULCAP JSON-LD file (default: resources/pbmc_jsonld_cl.json)",
    )
    parser.add_argument(
        "--sparql-endpoint",
        default=UBERGRAPH_ENDPOINT,
        help=f"UberGraph SPARQL endpoint (default: {UBERGRAPH_ENDPOINT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional TSV file to write the audit report",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=40,
        help="Number of PR IDs to query per SPARQL request (default: 40)",
    )
    return parser.parse_args()


def load_marker_definitions(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    definitions = []
    for raw_pr, meta in data.get("marker_definitions", {}).items():
        pr_curie = normalize_pr_curie(raw_pr)
        if not pr_curie:
            continue
        definitions.append(
            {
                "pr": pr_curie,
                "symbol": meta.get("symbol"),
                "name": meta.get("name"),
                "description": meta.get("description"),
            }
        )
    return definitions


def normalize_pr_curie(value: str | None) -> str | None:
    if not value:
        return None
    val = value.strip()
    if val.lower().startswith("pr:"):
        return f"pr:{val.split(':', 1)[1].zfill(7)}"
    if val.startswith("obo:PR_"):
        return f"pr:{val.split('PR_', 1)[1].zfill(7)}"
    if val.startswith("http://purl.obolibrary.org/obo/PR_"):
        return f"pr:{val.rsplit('_', 1)[1].zfill(7)}"
    return None


def curie_to_iri(curie: str) -> str:
    local = curie.split(":", 1)[1]
    return f"{PR_PREFIX}{local.zfill(7)}"


def iri_to_curie(iri: str) -> str:
    return f"pr:{iri.rsplit('_', 1)[1]}"


T = TypeVar("T")


def chunked(items: Iterable[T], size: int) -> Iterable[list[T]]:
    chunk: list[T] = []
    for item in items:
        chunk.append(item)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def run_sparql(endpoint: str, query: str) -> dict:
    response = requests.post(
        endpoint,
        data={"query": query},
        headers={"Accept": "application/sparql-results+json"},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def fetch_pr_term_data_chunk(pr_ids: list[str], endpoint: str) -> dict[str, dict]:
    if not pr_ids:
        return {}
    results: dict[str, dict] = defaultdict(lambda: {"label": None, "synonyms": set()})
    values = " ".join(f"<{curie_to_iri(curie)}>" for curie in pr_ids)
    query = f"""
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX oboInOwl: <http://www.geneontology.org/formats/oboInOwl#>
SELECT ?pr ?label ?syn
WHERE {{
  VALUES ?pr {{ {values} }}
  ?pr rdfs:isDefinedBy <{PR_ONTOLOGY_IRI}> .
  OPTIONAL {{ ?pr rdfs:label ?label }}
  OPTIONAL {{
    VALUES ?synProp {{ {' '.join(f'<{prop}>' for prop in SYNONYM_PROPS)} }}
    ?pr ?synProp ?syn
  }}
}}
"""
    data = run_sparql(endpoint, query)
    for binding in data.get("results", {}).get("bindings", []):
        pr_iri = binding["pr"]["value"]
        pr_curie = iri_to_curie(pr_iri)
        entry = results[pr_curie]
        if "label" in binding:
            entry["label"] = binding["label"]["value"]
        if "syn" in binding:
            entry["synonyms"].add(binding["syn"]["value"])
    return results


def sparql_escape(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return escaped


def find_synonym_matches(
    terms: dict[str, str], endpoint: str, chunk_size: int
) -> dict[str, list[dict]]:
    matches: dict[str, list[dict]] = defaultdict(list)
    term_items = list(terms.items())
    for chunk in chunked(term_items, chunk_size):
        values_rows = "\n    ".join(
            f'( "{sparql_escape(original)}" "{sparql_escape(original.lower())}" )'
            for key, original in chunk
        )
        query = f"""
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX oboInOwl: <http://www.geneontology.org/formats/oboInOwl#>
SELECT ?needle ?pr ?label ?synProp ?syn
WHERE {{
  VALUES (?needle ?needle_lc) {{
    {values_rows}
  }}
  ?pr rdfs:isDefinedBy <{PR_ONTOLOGY_IRI}> .
  VALUES ?synProp {{ {' '.join(f'<{prop}>' for prop in SYNONYM_PROPS)} }}
  ?pr ?synProp ?syn .
  FILTER(LCASE(STR(?syn)) = ?needle_lc)
  OPTIONAL {{ ?pr rdfs:label ?label }}
}}
"""
        data = run_sparql(endpoint, query)
        for binding in data.get("results", {}).get("bindings", []):
            needle = binding["needle"]["value"].lower()
            matches[needle].append(
                {
                    "pr": iri_to_curie(binding["pr"]["value"]),
                    "label": binding.get("label", {}).get("value"),
                    "synonym": binding["syn"]["value"],
                    "synonym_property": binding["synProp"]["value"],
                }
        )
    return matches


def format_suggestions(items: list[dict]) -> str:
    if not items:
        return "-"
    unique = []
    seen: set[str] = set()
    for item in items:
        key = item["pr"]
        if key in seen:
            continue
        seen.add(key)
        label = item.get("label") or "?"
        unique.append(f"{key} ({label})")
    return "; ".join(unique)


def build_rows_for_chunk(
    definitions: list[dict], pr_data: dict[str, dict]
) -> tuple[list[dict], dict[str, dict]]:
    chunk_rows: list[dict] = []
    missing_terms: dict[str, dict] = {}
    for marker in definitions:
        pr_id = marker["pr"]
        pr_info = pr_data.get(pr_id, {"label": None, "synonyms": set()})
        label = pr_info.get("label") or ""
        synonyms = pr_info.get("synonyms", set())
        available = set(synonyms)
        if label:
            available.add(label)
        normalized_available = {term.lower() for term in available if term}
        for field in ("symbol", "name"):
            value = marker.get(field)
            if not value:
                continue
            normalized_value = value.lower()
            match = normalized_value in normalized_available
            row = {
                "pr_id": pr_id,
                "field": field,
                "soulcap_value": value,
                "pr_label": label or "-",
                "pr_synonyms": "; ".join(sorted(synonyms)) if synonyms else "-",
                "status": "matched" if match else "unmatched",
                "suggestions": "-",
            }
            chunk_rows.append(row)
            if not match:
                missing_terms.setdefault(
                    normalized_value, {"original": value, "rows": []}
                )["rows"].append(row)
    return chunk_rows, missing_terms


def merge_missing_terms(
    target: dict[str, dict], additions: dict[str, dict]
) -> None:
    for key, data in additions.items():
        entry = target.setdefault(key, {"original": data["original"], "rows": []})
        entry["rows"].extend(data["rows"])


def audit_marker_definitions(
    definitions: list[dict], endpoint: str, chunk_size: int
) -> tuple[list[dict], dict[str, dict]]:
    rows: list[dict] = []
    missing_terms: dict[str, dict] = {}
    for chunk in chunked(definitions, chunk_size):
        pr_ids = [marker["pr"] for marker in chunk]
        pr_data = fetch_pr_term_data_chunk(pr_ids, endpoint)
        chunk_rows, chunk_missing = build_rows_for_chunk(chunk, pr_data)
        rows.extend(chunk_rows)
        merge_missing_terms(missing_terms, chunk_missing)
    return rows, missing_terms


def write_tsv(rows: list[dict], output: Path) -> None:
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
        raise SystemExit("No marker definitions found in PBMC JSON.")

    rows, missing_terms = audit_marker_definitions(
        definitions, args.sparql_endpoint, args.chunk_size
    )

    if missing_terms:
        search_map = {key: data["original"] for key, data in missing_terms.items()}
        suggestions = find_synonym_matches(
            search_map, args.sparql_endpoint, args.chunk_size
        )
        for key, data in missing_terms.items():
            suggestion_text = format_suggestions(suggestions.get(key, []))
            for row in data["rows"]:
                row["suggestions"] = suggestion_text

    unmatched = sum(1 for row in rows if row["status"] == "unmatched")
    print(
        f"Checked {len(rows)} marker name/symbol pairs "
        f"covering {len(definitions)} PR IDs; {unmatched} unmatched."
    )

    if args.output:
        write_tsv(rows, args.output)
        print(f"Wrote audit report to {args.output}")
    else:
        for row in rows:
            if row["status"] == "unmatched":
                print(
                    f"{row['pr_id']} {row['field']}='{row['soulcap_value']}' "
                    f"not found; suggestions: {row['suggestions']}"
                )


if __name__ == "__main__":
    main()
