#!/usr/bin/env python3
"""
Test script for the Cell Ontology Mapper

This script tests the core functionality of the mapper without requiring MCP setup.
"""

import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_server import CellOntologyMapper

def test_mapper():
    """Test the core mapping functionality."""
    print("Testing Cell Ontology Mapper...")
    
    try:
        # Initialize mapper
        mapper = CellOntologyMapper("resources/pbmc_jsonld_cl.json")
        print(f"✓ Loaded {len(mapper.populations)} cell populations")
        
        # Test cases from our previous work
        test_cases = [
            ("CD4+ CD25+ CD127low/-", "Regulatory T Cell"),
            ("CD14low CD16+", "Non-Classical Monocyte"),
            ("CD3+ CD4+ CD45RA+ CCR7+", "CD4+ Naive T Cell"),
            ("CD3+ CD4+ CD45RA- CCR7+", "CD4+ Central Memory T Cell"),
            ("CD19+ CD27++ CD38++", "Antibody Secreting Cell"),
            ("CD3- CD56+", "Natural Killer Cell"),
        ]
        
        print("\nTesting marker mappings:")
        print("-" * 60)
        
        for markers, expected in test_cases:
            matches = mapper.find_matches(markers)
            
            if matches:
                best_match = matches[0]
                population = best_match['population']
                match_info = best_match['match_info']
                
                print(f"Input: {markers}")
                print(f"Found: {population.label} ({population.cl_id})")
                print(f"Match: {match_info['match_type']} (score: {match_info['score']:.2f})")
                
                if expected.lower() in population.label.lower():
                    print("✓ Expected match found")
                else:
                    print(f"⚠ Expected '{expected}', got '{population.label}'")
            else:
                print(f"✗ No matches found for: {markers}")
            
            print("-" * 60)
        
        # Test marker parsing
        print("\nTesting marker parsing:")
        print("-" * 40)
        
        test_strings = [
            "CD3+ CD4+ CD8-",
            "CD3+,CD4+,CD8-",
            "CD3+/CD4+/CD8-",
            "CD25high CD127low",
            "CCR7+ CD45RA-"
        ]
        
        for test_string in test_strings:
            pos, neg = mapper.parse_markers(test_string)
            print(f"'{test_string}' → Positive: {pos}, Negative: {neg}")
        
        print("\n✓ All tests completed successfully!")
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = test_mapper()
    sys.exit(0 if success else 1)