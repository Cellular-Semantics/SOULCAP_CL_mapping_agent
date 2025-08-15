#!/usr/bin/env python3
"""
Cell Ontology Mapping MCP Server

This MCP server provides efficient querying capabilities for mapping cell surface markers
to Cell Ontology terms using the PBMC immunophenotyping dataset.
"""

import json
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.types import Resource, Tool, TextContent
import mcp.types as types
from pydantic import AnyUrl
import asyncio


@dataclass
class CellPopulation:
    """Represents a cell population with its markers and ontology mapping."""
    id: str
    label: str
    cl_id: str
    cl_label: str
    cl_definition: str
    lineage: str
    tier: int
    marker_expression: str
    positive_markers: List[str]
    negative_markers: List[str]
    parent_population: str
    exact_match: bool


class CellOntologyMapper:
    """Core mapper class for cell ontology queries."""
    
    def __init__(self, json_file_path: str):
        self.json_file_path = json_file_path
        self.populations: Dict[str, CellPopulation] = {}
        self.marker_definitions: Dict[str, Dict[str, str]] = {}
        self.load_data()
    
    def load_data(self):
        """Load and parse the JSON mapping file."""
        try:
            with open(self.json_file_path, 'r') as f:
                data = json.load(f)
            
            # Load marker definitions
            self.marker_definitions = data.get('marker_definitions', {})
            
            # Load populations
            for pop_data in data.get('populations', []):
                population = CellPopulation(
                    id=pop_data.get('@id', ''),
                    label=pop_data.get('rdfs:label', ''),
                    cl_id=pop_data.get('cl_id', ''),
                    cl_label=pop_data.get('cl_label', ''),
                    cl_definition=pop_data.get('cl_definition', ''),
                    lineage=pop_data.get('lineage', ''),
                    tier=pop_data.get('tier', 0),
                    marker_expression=pop_data.get('marker_expression', ''),
                    positive_markers=pop_data.get('positive_markers', []),
                    negative_markers=pop_data.get('negative_markers', []),
                    parent_population=pop_data.get('parent_population', ''),
                    exact_match=pop_data.get('exactMatch', False)
                )
                self.populations[population.id] = population
        except Exception as e:
            raise RuntimeError(f"Failed to load mapping data: {e}")
    
    def normalize_marker_string(self, marker_string: str) -> str:
        """Normalize marker string for consistent matching."""
        # Remove spaces, convert to uppercase, standardize separators
        normalized = re.sub(r'\s+', '', marker_string.upper())
        # Convert various separators to standard format
        normalized = re.sub(r'[,;/\+\-]+', '+', normalized)
        return normalized
    
    def parse_markers(self, marker_string: str) -> Tuple[List[str], List[str]]:
        """Parse marker string into positive and negative markers."""
        positive_markers = []
        negative_markers = []
        
        # Split by common separators and clean up
        markers = re.split(r'[,;\s/]+', marker_string.strip())
        
        for marker in markers:
            marker = marker.strip()
            if not marker:
                continue
                
            if marker.endswith('-') or marker.lower().endswith('negative') or marker.lower().endswith('neg'):
                # Negative marker
                clean_marker = re.sub(r'[-]$|negative$|neg$', '', marker, flags=re.IGNORECASE).strip()
                if clean_marker:
                    negative_markers.append(clean_marker.upper())
            elif marker.endswith('+') or marker.lower().endswith('positive') or marker.lower().endswith('pos'):
                # Positive marker
                clean_marker = re.sub(r'[\+]$|positive$|pos$', '', marker, flags=re.IGNORECASE).strip()
                if clean_marker:
                    positive_markers.append(clean_marker.upper())
            elif 'low' in marker.lower() or 'lo' in marker.lower():
                # Low expression treated as negative
                clean_marker = re.sub(r'low|lo', '', marker, flags=re.IGNORECASE).strip()
                if clean_marker:
                    negative_markers.append(clean_marker.upper())
            elif 'hi' in marker.lower() or 'high' in marker.lower():
                # High expression treated as positive
                clean_marker = re.sub(r'hi|high', '', marker, flags=re.IGNORECASE).strip()
                if clean_marker:
                    positive_markers.append(clean_marker.upper())
            else:
                # Default to positive if no polarity specified
                positive_markers.append(marker.upper())
        
        return positive_markers, negative_markers
    
    def find_matches(self, marker_string: str) -> List[Dict[str, Any]]:
        """Find cell populations matching the given marker string."""
        positive_markers, negative_markers = self.parse_markers(marker_string)
        matches = []
        
        for pop_id, population in self.populations.items():
            match_info = self._evaluate_match(population, positive_markers, negative_markers)
            if match_info['match_type'] != 'no_match':
                matches.append({
                    'population': population,
                    'match_info': match_info
                })
        
        # Sort by match quality (complete > partial > broader)
        match_priority = {'exact': 3, 'incomplete': 2, 'partial': 1}
        matches.sort(key=lambda x: match_priority.get(x['match_info']['match_type'], 0), reverse=True)
        matches.sort(key=lambda x: x['match_info']['score'], reverse=True)
        return matches
    
    def _evaluate_match(self, population: CellPopulation, pos_markers: List[str], neg_markers: List[str]) -> Dict[str, Any]:
        """Evaluate how well a population matches the given markers."""
        # Parse population marker expression
        pop_pos, pop_neg = self._parse_population_markers(population.marker_expression)
        
        # Convert marker names to standard format (handle CD197/CCR7, etc.)
        pos_markers_std = [self._standardize_marker_name(m) for m in pos_markers]
        neg_markers_std = [self._standardize_marker_name(m) for m in neg_markers]
        
        # Check matches
        pos_matches = set(pos_markers_std) & set(pop_pos)
        neg_matches = set(neg_markers_std) & set(pop_neg)
        total_input_markers = len(pos_markers_std) + len(neg_markers_std)
        total_matches = len(pos_matches) + len(neg_matches)

        if (
                (total_matches == 0) or
                (set(pop_pos).intersection(set(neg_markers_std))) or
                (set(pop_neg).intersection(set(pos_markers_std)))
            ):
            return {'match_type': 'no_match', 'score': 0}

        match_score = total_matches / max(total_input_markers, len(pop_pos) + len(pop_neg))
        # Check for exact match
        if ((set(pos_markers_std) == set(pop_pos)) and
            (set(neg_markers_std) == set(pop_neg))):
            return {
                'match_type': 'exact',
                'score': 1.0,
                'matched_positive': list(pos_matches),
                'matched_negative': list(neg_matches)
            }

        # Check for complete match
        elif (set(pos_markers_std).issubset(set(pop_pos)) and
            set(neg_markers_std).issubset(set(pop_neg)) and
            total_input_markers > 0):
            return {
                'match_type': 'incomplete',
                'score': match_score,
                'matched_positive': list(pos_matches),
                'matched_negative': list(neg_matches)
            }
        # Partial match
        else:
            return {
                'match_type': 'partial',
                'score': match_score,
                'matched_positive': list(pos_matches),
                'matched_negative': list(neg_matches),
                'missing_positive': list(set(pos_markers_std) - pos_matches),
                'missing_negative': list(set(neg_markers_std) - neg_matches)
            }
    
    def _parse_population_markers(self, marker_expr: str) -> Tuple[List[str], List[str]]:
        """Parse population marker expression into positive and negative markers."""
        if not marker_expr:
            return [], []
        
        # Remove 'live/' prefix and split by '/'
        expr = marker_expr.replace('live/', '')
        parts = expr.split('/')
        
        positive = []
        negative = []
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            if part.endswith('-'):
                marker = part[:-1]
                negative.append(self._standardize_marker_name(marker))
            elif part.endswith('+') or part.endswith('hi') or part.endswith('lo'):
                if part.endswith('lo'):
                    marker = part[:-2]
                    negative.append(self._standardize_marker_name(marker))
                else:
                    marker = part.rstrip('+hi')
                    positive.append(self._standardize_marker_name(marker))
            elif part.endswith('+/-'):
                marker = part[:-3]
                positive.append(self._standardize_marker_name(marker))
        
        return positive, negative
    
    def _standardize_marker_name(self, marker: str) -> str:
        """Standardize marker names (e.g., CCR7 -> CD197)."""
        ### Too much hard-wiring? (DOS)
        marker = marker.upper().strip()
        
        # Common synonyms
        synonyms = {
            'CCR7': 'CD197',
            'CCR3': 'CD193',
            'CCR4': 'CD194',
            'CXCR3': 'CD183',
            'CXCR5': 'CD185',
            'CRTH2': 'CD294',
            'C-KIT': 'CD117',
            'KIT': 'CD117',
        }
        
        return synonyms.get(marker, marker)


# Initialize the MCP server
server = Server("cell-ontology-mapper")

# Global mapper instance
mapper: Optional[CellOntologyMapper] = None


@server.list_resources()
async def handle_list_resources() -> list[Resource]:
    """List available resources."""
    return [
        Resource(
            uri=AnyUrl("file:///mapping-data"),
            name="Cell Ontology Mapping Data",
            description="PBMC immunophenotyping dataset with Cell Ontology integration",
            mimeType="application/json"
        )
    ]


@server.read_resource()
async def handle_read_resource(uri: AnyUrl) -> str:
    """Read resource content."""
    if str(uri) == "file:///mapping-data":
        if mapper:
            return f"Loaded {len(mapper.populations)} cell populations with Cell Ontology mappings"
        return "Mapping data not loaded"
    
    raise ValueError(f"Unknown resource: {uri}")


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="map_markers",
            description="Map cell surface markers to Cell Ontology terms",
            inputSchema={
                "type": "object",
                "properties": {
                    "markers": {
                        "type": "string",
                        "description": "Cell surface markers (e.g., 'CD3+ CD4+ CD45RA- CCR7+')"
                    }
                },
                "required": ["markers"]
            }
        ),
        Tool(
            name="search_populations",
            description="Search for cell populations by name or ontology term",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (population name, CL term, etc.)"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_population_details",
            description="Get detailed information about a specific cell population",
            inputSchema={
                "type": "object",
                "properties": {
                    "population_id": {
                        "type": "string",
                        "description": "Population ID (e.g., 'cd4_naive', 'treg')"
                    }
                },
                "required": ["population_id"]
            }
        ),
        Tool(
            name="list_lineages",
            description="List all available cell lineages",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Handle tool calls."""
    global mapper
    
    if not mapper:
        return [TextContent(type="text", text="Error: Mapping data not loaded. Please initialize the mapper first.")]
    
    if name == "map_markers":
        markers = arguments.get("markers", "")
        matches = mapper.find_matches(markers)
        
        if not matches:
            return [TextContent(type="text", text=f"No matches found for markers: {markers}")]
        
        result = f"Mapping results for '{markers}':\n\n"
        for i, match in enumerate(matches[:5], 1):  # Limit to top 5 matches
            pop = match['population']
            info = match['match_info']
            
            result += f"{i}. {pop.label}\n"
            result += f"   Cell Ontology ID: {pop.cl_id}\n"
            result += f"   Cell Ontology Label: {pop.cl_label}\n"
            result += f"   Match Type: {info['match_type']}\n"
            result += f"   Match Score: {info['score']:.2f}\n"
            result += f"   Marker Expression: {pop.marker_expression}\n"
            result += f"   Definition: {pop.cl_definition}\n\n"
        
        return [TextContent(type="text", text=result)]
    
    elif name == "search_populations":
        query = arguments.get("query", "").lower()
        results = []
        
        for pop_id, pop in mapper.populations.items():
            if (query in pop.label.lower() or 
                query in pop.cl_label.lower() or 
                query in pop.cl_id.lower() or
                query in pop_id.lower()):
                results.append(pop)
        
        if not results:
            return [TextContent(type="text", text=f"No populations found matching: {query}")]
        
        result = f"Search results for '{query}':\n\n"
        for i, pop in enumerate(results[:10], 1):  # Limit to top 10
            result += f"{i}. {pop.label} ({pop.id})\n"
            result += f"   CL: {pop.cl_id} - {pop.cl_label}\n"
            result += f"   Lineage: {pop.lineage}\n\n"
        
        return [TextContent(type="text", text=result)]
    
    elif name == "get_population_details":
        population_id = arguments.get("population_id", "")
        
        if population_id not in mapper.populations:
            return [TextContent(type="text", text=f"Population not found: {population_id}")]
        
        pop = mapper.populations[population_id]
        
        result = f"Population Details: {pop.label}\n"
        result += f"ID: {pop.id}\n"
        result += f"Cell Ontology ID: {pop.cl_id}\n"
        result += f"Cell Ontology Label: {pop.cl_label}\n"
        result += f"Definition: {pop.cl_definition}\n"
        result += f"Lineage: {pop.lineage}\n"
        result += f"Tier: {pop.tier}\n"
        result += f"Marker Expression: {pop.marker_expression}\n"
        result += f"Parent Population: {pop.parent_population}\n"
        result += f"Exact Match: {pop.exact_match}\n"
        
        return [TextContent(type="text", text=result)]
    
    elif name == "list_lineages":
        lineages = set()
        for pop in mapper.populations.values():
            if pop.lineage:
                lineages.add(pop.lineage)
        
        result = "Available Cell Lineages:\n\n"
        for lineage in sorted(lineages):
            count = sum(1 for pop in mapper.populations.values() if pop.lineage == lineage)
            result += f"- {lineage} ({count} populations)\n"
        
        return [TextContent(type="text", text=result)]
    
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    """Main function to run the MCP server."""
    global mapper
    
    # Initialize the mapper
    json_file_path = "resources/pbmc_jsonld_cl.json"
    try:
        mapper = CellOntologyMapper(json_file_path)
        print(f"Loaded {len(mapper.populations)} cell populations")
    except Exception as e:
        print(f"Failed to load mapping data: {e}")
        return
    
    # Run the server
    from mcp.server.stdio import stdio_server
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="cell-ontology-mapper",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())