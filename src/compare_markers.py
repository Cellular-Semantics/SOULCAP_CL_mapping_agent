"""
Generate a comparison report between PBMC JSON-LD marker assignments and
Cell Ontology PR marker annotations.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

import requests

POSITIVE_RELATIONS = {
    "RO:0002104",  # has plasma membrane part
    "RO:0015015",  # has high plasma membrane amount
}

NEGATIVE_RELATIONS = {
    "CL:4030045",  # lacks part
    "CL:4030046",  # lacks plasma membrane part
    "RO:0015016",  # has low plasma membrane amount
}

REL_LINE_PATTERN = re.compile(r"^(?P<pred>\S+)\s+(?P<obj>\S+)")
REDUNDANT_GRAPH = "<http://reasoner.renci.org/redundant>"
UBERGRAPH_ENDPOINT = "https://ubergraph.apps.renci.org/sparql"


def load_pbmc_populations(path: Path) -> tuple[list[dict], dict[str, dict]]:
    data = json.loads(path.read_text())
    marker_defs = {
        k.lower(): v for k, v in data.get("marker_definitions", {}).items()
    }
    populations = []
    for entry in data.get("populations", []):
        cl_id = normalize_cl_id(entry.get("cl_id"))
        if not cl_id:
            continue
        populations.append(
            {
                "id": entry.get("@id"),
                "label": entry.get("rdfs:label"),
                "cl_id": cl_id,
                "positive_markers": normalize_marker_list(entry.get("positive_markers")),
                "negative_markers": normalize_marker_list(entry.get("negative_markers")),
            }
        )
    return populations, marker_defs


def normalize_marker_list(items: list | None) -> set[str]:
    markers: set[str] = set()
    if not items:
        return markers
    for item in items:
        marker = normalize_pr_id(item)
        if marker:
            markers.add(marker)
    return markers


def parse_cl_markers(path: Path) -> dict[str, dict[str, set[str]]]:
    positive = defaultdict(set)
    negative = defaultdict(set)
    current_id: str | None = None

    with path.open() as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line == "[Term]":
                current_id = None
                continue
            if line.startswith("id: "):
                current_id = line.split(" ", 1)[1]
                continue
            if not current_id or not current_id.startswith("CL:"):
                continue
            if line.startswith("relationship: "):
                rel_body = line.split(" ", 1)[1]
                rel_core = rel_body.split(" ! ", 1)[0]
                match = REL_LINE_PATTERN.match(rel_core)
                if not match:
                    continue
                predicate = match.group("pred")
                obj = strip_qualifiers(match.group("obj"))
                pr_id = normalize_pr_id(obj)
                if not pr_id:
                    continue
                if predicate in POSITIVE_RELATIONS:
                    positive[current_id].add(pr_id)
                if predicate in NEGATIVE_RELATIONS:
                    negative[current_id].add(pr_id)

    combined: dict[str, dict[str, set[str]]] = {}
    for cl_id in set(positive) | set(negative):
        combined[cl_id] = {
            "positive": positive.get(cl_id, set()),
            "negative": negative.get(cl_id, set()),
        }
    return combined


def fetch_markers_from_ubergraph(
    endpoint: str = UBERGRAPH_ENDPOINT,
) -> dict[str, dict[str, set[str]]]:
    relation_iris = {
        _relation_uri(rel) for rel in POSITIVE_RELATIONS | NEGATIVE_RELATIONS
    }
    values = " ".join(f"<{iri}>" for iri in relation_iris)
    query = f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT DISTINCT ?cl ?relation ?pr
FROM {REDUNDANT_GRAPH}
WHERE {{
  VALUES ?relation {{ {values} }}
  ?cl ?relation ?pr .
  FILTER(STRSTARTS(STR(?cl), "http://purl.obolibrary.org/obo/CL_"))
  FILTER(STRSTARTS(STR(?pr), "http://purl.obolibrary.org/obo/PR_"))
}}
"""
    response = requests.post(
        endpoint,
        data={"query": query},
        headers={"Accept": "application/sparql-results+json"},
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    positive = defaultdict(set)
    negative = defaultdict(set)
    for binding in data.get("results", {}).get("bindings", []):
        cl_iri = binding["cl"]["value"]
        relation_iri = binding["relation"]["value"]
        pr_iri = binding["pr"]["value"]
        cl_curie = _iri_to_curie(cl_iri, "CL")
        pr_curie = _iri_to_curie(pr_iri, "PR")
        rel_curie = _iri_to_curie(relation_iri, None)
        if not cl_curie or not pr_curie or not rel_curie:
            continue
        if rel_curie in POSITIVE_RELATIONS:
            positive[cl_curie].add(pr_curie.lower())
        if rel_curie in NEGATIVE_RELATIONS:
            negative[cl_curie].add(pr_curie.lower())

    combined: dict[str, dict[str, set[str]]] = {}
    for cl_id in set(positive) | set(negative):
        combined[cl_id] = {
            "positive": positive.get(cl_id, set()),
            "negative": negative.get(cl_id, set()),
        }
    return combined


def _relation_uri(curie: str) -> str:
    if ":" not in curie:
        return curie
    prefix, local = curie.split(":", 1)
    if local.isdigit():
        local = local.zfill(7)
    return f"http://purl.obolibrary.org/obo/{prefix}_{local}"


def _iri_to_curie(iri: str, expected_prefix: str | None) -> str | None:
    if not iri.startswith("http://purl.obolibrary.org/obo/"):
        return None
    suffix = iri.rsplit("/", 1)[1]
    if "_" not in suffix:
        return None
    prefix, local = suffix.split("_", 1)
    curie = f"{prefix}:{local}"
    if expected_prefix and prefix != expected_prefix:
        return None
    return curie


def strip_qualifiers(value: str) -> str:
    if "{" in value:
        value = value.split("{", 1)[0]
    return value.strip()


def normalize_pr_id(value: str | None) -> str | None:
    if not value:
        return None
    val = value.strip()
    if val.startswith("pr:"):
        return val.lower()
    if val.startswith("PR:"):
        return f"pr:{val.split(':', 1)[1]}"
    if val.startswith("obo:PR_"):
        return f"pr:{val.split('PR_', 1)[1]}"
    return None


def normalize_cl_id(value: str | None) -> str | None:
    if not value:
        return None
    val = value.strip()
    if val.lower().startswith("cl:"):
        return f"CL:{val.split(':', 1)[1].zfill(7)}"
    if val.startswith("http://purl.obolibrary.org/obo/CL_"):
        return f"CL:{val.rsplit('_', 1)[1]}"
    return None


def format_marker_list(
    markers: set[str], marker_defs: dict[str, dict]
) -> str:
    if not markers:
        return "-"
    ordered = sorted(markers)
    formatted = []
    for marker in ordered:
        meta = marker_defs.get(marker, {})
        symbol = meta.get("symbol")
        if symbol:
            formatted.append(f"{symbol} ({marker})")
        else:
            formatted.append(marker)
    return "; ".join(formatted)


def compare_markers(
    populations: list[dict],
    cl_markers: dict[str, dict[str, set[str]]],
    marker_defs: dict[str, dict],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for pop in populations:
        cl_id = pop["cl_id"]
        cl_data = cl_markers.get(cl_id)
        if not cl_data:
            rows.append(
                {
                    "population_id": pop.get("id", ""),
                    "population_label": pop.get("label", ""),
                    "cl_id": cl_id,
                    "matching_positive": "-",
                    "missing_positive": format_marker_list(
                        pop["positive_markers"], marker_defs
                    ),
                    "extra_positive": "CL term not found",
                    "matching_negative": "-",
                    "missing_negative": format_marker_list(
                        pop["negative_markers"], marker_defs
                    ),
                    "extra_negative": "CL term not found",
                }
            )
            continue

        matching_pos = pop["positive_markers"] & cl_data["positive"]
        missing_pos = pop["positive_markers"] - cl_data["positive"]
        extra_pos = cl_data["positive"] - pop["positive_markers"]
        matching_neg = pop["negative_markers"] & cl_data["negative"]
        missing_neg = pop["negative_markers"] - cl_data["negative"]
        extra_neg = cl_data["negative"] - pop["negative_markers"]

        rows.append(
            {
                "population_id": pop.get("id", ""),
                "population_label": pop.get("label", ""),
                "cl_id": cl_id,
                "matching_positive": format_marker_list(matching_pos, marker_defs),
                "missing_positive": format_marker_list(missing_pos, marker_defs),
                "extra_positive": format_marker_list(extra_pos, marker_defs),
                "matching_negative": format_marker_list(matching_neg, marker_defs),
                "missing_negative": format_marker_list(missing_neg, marker_defs),
                "extra_negative": format_marker_list(extra_neg, marker_defs),
            }
        )
    return rows


def write_report(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        output_path.write_text(
            "population_id\tpopulation_label\tcl_id\tmatching_positive\tmissing_positive\textra_positive\tmatching_negative\tmissing_negative\textra_negative\n"
        )
        return
    with output_path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "population_id",
                "population_label",
                "cl_id",
                "matching_positive",
                "missing_positive",
                "extra_positive",
                "matching_negative",
                "missing_negative",
                "extra_negative",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pbmc-json",
        type=Path,
        default=Path("resources/pbmc_jsonld_cl.json"),
    )
    parser.add_argument(
        "--cl-obo",
        type=Path,
        default=Path("resources/cl-full.obo"),
    )
    parser.add_argument(
        "--source",
        choices=["obo", "ubergraph"],
        default="obo",
        help="Marker source: local OBO parsing or UberGraph SPARQL (default: obo)",
    )
    parser.add_argument(
        "--sparql-endpoint",
        default=UBERGRAPH_ENDPOINT,
        help=f"UberGraph SPARQL endpoint (default: {UBERGRAPH_ENDPOINT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("resources/marker_mismatch_report.tsv"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    populations, marker_defs = load_pbmc_populations(args.pbmc_json)
    if args.source == "ubergraph":
        cl_markers = fetch_markers_from_ubergraph(args.sparql_endpoint)
    else:
        cl_markers = parse_cl_markers(args.cl_obo)
    rows = compare_markers(populations, cl_markers, marker_defs)
    write_report(rows, args.output)
    print(f"Wrote {len(rows)} mismatch rows to {args.output}")


if __name__ == "__main__":
    main()
