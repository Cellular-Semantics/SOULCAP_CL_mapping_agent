# Cell Ontology Mapping Agent

An MCP (Model Context Protocol) server for efficient mapping of cell surface markers to Cell Ontology terms using the PBMC immunophenotyping dataset.

## Overview

This tool helps map input strings consisting of cell surface marker combinations (e.g., "CD3+ CD4+ CD45RA- CCR7+") to standardized Cell Ontology terms. It's designed for researchers working with flow cytometry data who need to standardize their cell population definitions.

## Features

- **Efficient Marker Mapping**: Maps cell surface marker combinations to Cell Ontology terms
- **Flexible Input Parsing**: Handles various marker formats and separators
- **Match Quality Assessment**: Distinguishes between complete, partial, and broader matches
- **MCP Integration**: Seamlessly integrates with Claude Code for interactive queries
- **Comprehensive Dataset**: Uses standardized PBMC immunophenotyping data with Cell Ontology integration

## Installation

### Prerequisites

- Python 3.8 or higher
- pip package manager

### Setup

1. **Clone or download this repository**
   ```bash
   git clone <repository-url>
   cd SOULCAP_CL_mapping_agent
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Claude + MCP

```bash
python mcp_server.py &
claude mcp add soulcap-mapper -- python mcp_server.py
claude
```


1. **Start a mapping session**:
   ```
   Map the markers "CD3+ CD4+ CD45RA+ CCR7+" to Cell Ontology terms
   ```

2. **Search for populations**:
   ```
   Search for all memory T cell populations
   ```

3. **Get detailed information**:
   ```
   Show me details about the regulatory T cell population
   ```
   
### Use the Python library directly

```python
# Test mapping
from mcp_server import CellOntologyMapper
import pandas as pd
mapper = CellOntologyMapper("resources/pbmc_jsonld_cl.json")
matches = mapper.find_matches("CD3+ CD4+ CD45RA- CCR7+")
print(f"Found {len(matches)} matches")
out = [{ 'score': match['match_info']['score'], 
         'type': match['match_info']['match_type'], 
         'markers': match['population'].marker_expression, 
         'label': match['population'].label} for match in matches]
df = pd.DataFrame.from_records(out)
df
```

score | type | markers | label
-- | -- | -- | --
0.5 | incomplete | live/CD45+/CD3+/CD4+/CD8-/CD197+/CD45RA+ | CD4+ Naive T Cell
0.5 | incomplete | live/CD45+/CD3+/CD4+/CD8-/CD197+/CD45RA- | CD4+ Central Memory T Cell
0.5 | incomplete | live/CD45+/CD3+/CD4+/CD8-/CD197-/CD45RA- | CD4+ Effector Memory T Cell
0.5 | incomplete | live/CD45+/CD3+/CD4+/CD8-/CD197-/CD45RA+ | CD4+ Terminal Effector Memory T Cell
0.43 | incomplete | live/CD45+/CD3+/CD56-/TCRgd-/TCR Va7.2-/CD4+/CD8- | CD4+ T Cell

## Details

### Basic Marker Mapping

The primary function is to map cell surface marker combinations to Cell Ontology terms:

```python
# Example marker inputs:
"CD3+ CD4+ CD45RA- CCR7+"     # → CD4+ Central Memory T Cell (cl:0000904)
"CD4+ CD25+ CD127low/-"       # → Regulatory T Cell (cl:0000815)
"CD14low CD16+"               # → Non-Classical Monocyte (cl:0000875)
"CD19+ CD27++ CD38++"         # → Antibody Secreting Cell (cl:0000946)
```

### Available MCP Tools

#### 1. `map_markers`
Maps cell surface markers to Cell Ontology terms.

**Input**: `markers` (string) - Cell surface markers (e.g., 'CD3+ CD4+ CD45RA- CCR7+')

**Example**:
```json
{
  "markers": "CD3+ CD4+ CD45RA- CCR7+"
}
```

#### 2. `search_populations`
Search for cell populations by name or ontology term.

**Input**: `query` (string) - Search query (population name, CL term, etc.)

**Example**:
```json
{
  "query": "memory T cell"
}
```

#### 3. `get_population_details`
Get detailed information about a specific cell population.

**Input**: `population_id` (string) - Population ID (e.g., 'cd4_naive', 'treg')

**Example**:
```json
{
  "population_id": "treg"
}
```

#### 4. `list_lineages`
List all available cell lineages.

**Input**: None required

### Supported Marker Formats

The system handles various marker input formats:

- **Standard format**: `CD3+ CD4+ CD8-`
- **With separators**: `CD3+,CD4+,CD8-` or `CD3+/CD4+/CD8-`
- **Expression levels**: `CD25high`, `CD127low`, `CD38hi`
- **Alternative names**: `CCR7+` (converted to `CD197+`)

### Match Types

The system provides three types of matches:

1. **Exact Match**: Input markers match the entire population definition.
2. **Incomplete Match**: All input markers are in the population definition which contains additional markers.
3. **Partial Match**: Some input markers are in the population definition, which may also contain additional markers.

No match is made if either none of the markers are present 
or if a positive marker is negative for the population of vice versa

## Dataset Structure

The mapping is based on a comprehensive PBMC immunophenotyping dataset (`resources/pbmc_jsonld_cl.json`) that includes:

- **Cell Populations**: 40+ standardized immune cell populations
- **Cell Ontology Integration**: Direct mapping to CL terms
- **Marker Definitions**: Standardized marker symbols and descriptions
- **Lineage Hierarchy**: Organized by cell lineage (T cells, B cells, NK cells, etc.)
- **Validation Metadata**: Curation and validation information

### Example Population Entry

```json
{
  "@id": "treg",
  "@type": "pbmc:ImmunePopulation",
  "rdfs:label": "Regulatory T Cell",
  "cl_id": "cl:0000815",
  "cl_label": "regulatory T cell",
  "cl_definition": "A T cell which regulates overall immune responses...",
  "lineage": "t_cells",
  "tier": 4,
  "positive_markers": ["pr:000001309", "pr:000000927", "pr:000000932", "pr:000001823"],
  "marker_expression": "live/CD45+/CD3+/CD4+/CD8-/CD25+/CD127lo/-",
  "negative_markers": ["pr:000001002", "pr:000000949"],
  "parent_population": "cd4t",
  "exactMatch": true
}
```
:



## Development

### Running the Server Directly

For testing and development:

```bash
python mcp_server.py
```

### Adding New Populations

Please post a ticket to request a new population.  
Follow the fields in the population example above.


## Common Use Cases

### Flow Cytometry Panel Design
- Validate marker combinations against standard definitions
- Identify overlapping populations in multi-parameter panels
- Standardize gating strategies across laboratories

### Data Analysis and Reporting
- Convert local gating definitions to standard ontology terms
- Generate standardized population names for publications
- Ensure consistent terminology across datasets

### Meta-Analysis and Data Integration
- Harmonize cell population definitions across studies
- Map historical data to current ontology standards
- Enable cross-study comparisons

## Troubleshooting

### Common Issues

1. **No matches found**
   - Check marker spelling and format
   - Try using standard CD nomenclature
   - Consider if markers define a known population

2. **Multiple partial matches**
   - Review match scores and descriptions
   - Consider biological context and lineage
   - Check parent-child relationships in the ontology

3. **MCP server not connecting**
   - Verify Python environment and dependencies
   - Check file paths in configuration
   - Ensure JSON dataset is accessible

### Getting Help

- Check the `marker_comparison.tsv` file for examples of successful mappings
- Review the JSON dataset structure in `resources/pbmc_jsonld_cl.json`
- Consult Cell Ontology documentation: http://purl.obolibrary.org/obo/cl.owl

## Contributing

To contribute improvements:

1. Fork the repository
2. Add new populations or improve matching algorithms
3. Test thoroughly with diverse marker combinations
4. Submit pull requests with clear documentation

## License

This project is released under the Creative Commons Attribution 4.0 International License, consistent with the underlying Cell Ontology and PBMC standards datasets.

## Citation

When using this tool in research, please cite:
- The Cell Ontology: http://www.obofoundry.org/ontology/cl.html
- This mapping agent and associated PBMC immunophenotyping dataset

---

For questions or support, please refer to the issues section of this repository.