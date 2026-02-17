"""
Utility to convert PBMC JSON-LD definitions into standard RDF/OWL serializations.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from rdflib import Graph
from rdflib.collection import Collection
from rdflib.namespace import Namespace, NamespaceManager
from rdflib.term import BNode, Literal, Node, URIRef

DEFAULT_BASE_IRI = "http://pbmc-standards.org/"

CURIE_PREFIX_MAP: dict[str, str] = {
    "pbmc": "http://pbmc-standards.org/terms/",
    "cl": "http://purl.obolibrary.org/obo/CL_",
    "pr": "http://purl.obolibrary.org/obo/PR_",
    "go": "http://purl.obolibrary.org/obo/GO_",
    "hgnc": "http://identifiers.org/hgnc.symbol/",
}

MARKER_PROPERTIES = [
    URIRef("http://pbmc-standards.org/terms/positiveMarkers"),
    URIRef("http://pbmc-standards.org/terms/negativeMarkers"),
    URIRef("http://pbmc-standards.org/terms/conditionalMarkers"),
]
LINEAGE_PROPERTY = URIRef("http://pbmc-standards.org/terms/lineage")


def convert_jsonld(
    input_path: Path,
    output_dir: Path,
    formats: Sequence[tuple[str, str]],
    base_iri: str = DEFAULT_BASE_IRI,
) -> list[Path]:
    """Convert JSON-LD file into a set of RDF serializations."""
    graph = Graph()
    graph.parse(input_path.as_posix(), format="json-ld", base=base_iri)
    graph = _expand_curie_uris(graph)
    graph = _flatten_marker_lists(graph)
    graph = _normalize_lineage_values(graph)
    graph = _sanitize_namespaces(graph)

    output_dir.mkdir(parents=True, exist_ok=True)

    generated_files: list[Path] = []
    for suffix, rdf_format in formats:
        output_file = output_dir / f"{input_path.stem}{suffix}"
        graph.serialize(destination=output_file.as_posix(), format=rdf_format)
        generated_files.append(output_file)

    return generated_files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("resources/pbmc_jsonld_cl.json"),
        help="JSON-LD file to convert (default: resources/pbmc_jsonld_cl.json)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("resources"),
        help="Directory for converted files (default: resources)",
    )
    parser.add_argument(
        "--base-iri",
        default=DEFAULT_BASE_IRI,
        help=f"Base IRI to use while parsing JSON-LD (default: {DEFAULT_BASE_IRI})",
    )
    return parser.parse_args()


def _sanitize_namespaces(graph: Graph) -> Graph:
    """Rebind unsafe prefixes to keep RDF/XML serialization happy."""
    original_namespaces = list(graph.namespace_manager.namespaces())
    safe_manager = NamespaceManager(graph)
    graph.namespace_manager = safe_manager

    for prefix, namespace in original_namespaces:
        if prefix == "pr":
            continue
        safe_manager.bind(prefix, namespace, replace=True)

    safe_manager.bind("obo", Namespace("http://purl.obolibrary.org/obo/"), replace=True)

    return graph


def _expand_curie_uris(graph: Graph) -> Graph:
    updated_triples: list[tuple[Node, Node, Node]] = []
    changed = False
    for triple in graph:
        new_triple = tuple(_expand_curie_term(term) for term in triple)
        if new_triple != triple:
            changed = True
        updated_triples.append(new_triple)

    if not changed:
        return graph

    graph.remove((None, None, None))
    for triple in updated_triples:
        graph.add(triple)

    return graph


def _expand_curie_term(term: Node) -> Node:
    if isinstance(term, URIRef):
        if _looks_like_absolute(str(term)):
            return term
        iri = _curie_to_iri(str(term))
        if iri is not None:
            return iri
    return term


def _flatten_marker_lists(graph: Graph) -> Graph:
    """Replace RDF list values for marker properties with repeated statements."""
    for prop in MARKER_PROPERTIES:
        for subject, _, list_node in list(graph.triples((None, prop, None))):
            if not isinstance(list_node, BNode):
                continue
            try:
                collection = Collection(graph, list_node)
            except Exception:
                continue
            members = list(collection)
            collection.clear()
            graph.remove((subject, prop, list_node))
            for member in members:
                graph.add((subject, prop, member))
    return graph


def _normalize_lineage_values(graph: Graph) -> Graph:
    """Convert lineage values (literal or base-relative IRIs) into pbmc IRIs."""
    for subject, _, lineage_value in list(graph.triples((None, LINEAGE_PROPERTY, None))):
        new_value: URIRef | None = None
        if isinstance(lineage_value, Literal):
            new_value = _curie_to_iri(str(lineage_value))
        elif isinstance(lineage_value, URIRef):
            new_value = _coerce_pbmc_uri(lineage_value)
        if new_value is None or new_value == lineage_value:
            continue
        graph.remove((subject, LINEAGE_PROPERTY, lineage_value))
        graph.add((subject, LINEAGE_PROPERTY, new_value))
    return graph


def _curie_to_iri(value: str) -> URIRef | None:
    if _looks_like_absolute(value):
        return URIRef(value)
    prefix, sep, local = value.partition(":")
    if sep and prefix in CURIE_PREFIX_MAP:
        return URIRef(f"{CURIE_PREFIX_MAP[prefix]}{local}")
    if not sep and value:
        # treat bare tokens as pbmc:local identifiers
        return URIRef(f"{CURIE_PREFIX_MAP['pbmc']}{value}")
    return None


def _looks_like_absolute(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _coerce_pbmc_uri(node: URIRef) -> URIRef | None:
    iri = str(node)
    pbmc_prefix = CURIE_PREFIX_MAP["pbmc"]
    if iri.startswith(pbmc_prefix):
        return node
    if iri.startswith(DEFAULT_BASE_IRI):
        remainder = iri[len(DEFAULT_BASE_IRI) :]
        if remainder:
            return URIRef(f"{pbmc_prefix}{remainder}")
    return None


def main() -> None:
    args = parse_args()
    formats = [
        (".ttl", "turtle"),
        (".owl", "pretty-xml"),
    ]

    generated = convert_jsonld(
        input_path=args.input,
        output_dir=args.output_dir,
        formats=formats,
        base_iri=args.base_iri,
    )

    for path in generated:
        print(f"Generated {path}")


if __name__ == "__main__":
    main()
