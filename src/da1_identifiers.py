import re
from typing import Any, Dict, List
import xml.etree.ElementTree as ET
import os
from git import Repo
import csv

from src.srcml_runner import run_srcml_on_text, run_srcml_on_repo_file

def strip_namespace(tag: str) -> str:
    """Remove namespace prefix from tag."""
    if isinstance(tag, str) and '}' in tag:
        return tag.split('}', 1)[1]
    return tag

def _get_convention(name: str) -> str:
    """Determine the naming convention of an identifier."""
    if not name:
        return "other"
    if name.isupper() and ("_" in name or len(name) > 1):
        return "SCREAMING_SNAKE"
    if name.islower():
        return "snake_case"
    if "_" not in name:
        if name[0].islower() and any(c.isupper() for c in name):
            return "camelCase"
        if name[0].isupper():
            return "PascalCase"
    return "other"

def _tokenize(name: str) -> List[str]:
    """Split an identifier by underscore and case boundaries."""
    if not name:
        return []
    parts = [p for p in name.split('_') if p]
    tokens = []
    for part in parts:
        spaced = re.sub(r'([A-Z])', r' \1', part)
        tokens.extend([t.lower() for t in spaced.split() if t])
    return tokens

def extract_identifiers_dom(xml_str: str) -> List[Dict[str, Any]]:
    """Extract identifier rows using a DOM-style approach (ElementTree/XPath-style finds).
  
    Parameters:
    - xml_str: srcML XML document as string
    
    Returns:
    - List of identifier dicts, each with keys:
      - name (str): identifier text
      - kind (str): one of 'function', 'parameter', 'variable', 'class'
      - convention (str): naming convention detected
      - length (int): character count
      - n_tokens (int): token count after splitting
      - scope (str): one of 'global', 'local', 'parameter'
    
    Behavior:
    - Parse the entire XML tree with ElementTree
    - Use `.iter()` or `.findall()` to locate function/class/parameter/decl nodes
    - For each <name> node, classify its context (function name vs parameter name vs variable)
    - Return one row per identifier found
    
    Examples:
    >>> xml = '<unit><function><name>process</name></function></unit>'
    >>> ids = extract_identifiers_dom(xml)
    >>> ids[0]['name']
    'process'
    >>> ids[0]['kind']
    'function'
    
    Implementation hints:
    - Use `ET.fromstring(xml_str)` to parse
    - Namespace-aware: strip namespace prefixes with helper (e.g., tag.rsplit('}', 1)[1])
    - Iterate over functions first, then parameters within, then local variables
    - Check parent/ancestor tags to determine context (function vs class vs global)
    """
    root = ET.fromstring(xml_str)
    identifiers = []

    def visit(element, current_scope="global"):
        tag = strip_namespace(element.tag)

        def get_name_text(elem):
            for child in elem:
                if strip_namespace(child.tag) == 'name':
                    return ''.join(child.itertext()).strip()
            return None
        if tag == 'function':
            name_text = get_name_text(element)
            if name_text:
                identifiers.append({
                    'name': name_text,
                    'kind': 'function',
                    'convention': _get_convention(name_text),
                    'length': len(name_text),
                    'n_tokens': len(_tokenize(name_text)),
                    'scope': 'global' 
                })
            for child in element:
                next_scope = "local" if strip_namespace(child.tag) == "block" else current_scope
                visit(child, next_scope)
            return
        elif tag == 'class':
            name_text = get_name_text(element)
            if name_text:
                identifiers.append({
                    'name': name_text,
                    'kind': 'class',
                    'convention': _get_convention(name_text),
                    'length': len(name_text),
                    'n_tokens': len(_tokenize(name_text)),
                    'scope': current_scope 
                })
            for child in element:
                visit(child, current_scope)
            return

        elif tag == 'parameter_list':
            for child in element:
                visit(child, "parameter")
            return

        elif tag == 'decl':
            kind = 'parameter' if current_scope == 'parameter' else 'variable'
            name_text = get_name_text(element)
            
            if name_text:
                identifiers.append({
                    'name': name_text,
                    'kind': kind,
                    'convention': _get_convention(name_text),
                    'length': len(name_text),
                    'n_tokens': len(_tokenize(name_text)),
                    'scope': current_scope
                })
            for child in element:
                visit(child, current_scope)
            return

        for child in element:
            next_scope = "local" if strip_namespace(child.tag) == "block" else current_scope
            visit(child, next_scope)

    visit(root, "global")
    return identifiers

def aggregate_identifier_features(identifiers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute file-level aggregate metrics from identifier rows.
    
    Parameters:
    - identifiers: list of identifier dicts from extract_identifiers_dom/sax
    
    Returns:
    - dict with keys:
      - n_identifiers (int): total count
      - avg_identifier_length (float): mean character length
      - avg_tokens_per_identifier (float): mean tokens per name
      - vocab_size (int): unique normalized tokens
      - vocab_diversity (float): unique tokens / total tokens (0.0 to 1.0)
      - pct_snake_case (float): fraction using snake_case
      - pct_camel_case (float): fraction using camelCase
      - pct_pascal_case (float): fraction using PascalCase
    
    Behavior:
    - Return all metrics as 0/0.0 if identifiers list is empty
    - Compute means with simple arithmetic (sum / count)
    - Vocabulary = set of all unique tokens (after lowercasing and splitting)
    - Diversity = len(vocab) / total_token_count (avoid division by zero)
    
    Examples:
    >>> ids = [{'name': 'getUser', 'convention': 'camelCase', 'length': 7, 'tokens': ['get', 'user']}]
    >>> agg = aggregate_identifier_features(ids)
    >>> agg['n_identifiers']
    1
    >>> agg['pct_camel_case']
    1.0
    
    Implementation hints:
    - Use sum() and len() for averages
    - Build vocab with set comprehension: {token for row in identifiers for token in row['tokens']}
    - Count conventions with list comprehension and sum(1 for ...)
    """
    if not identifiers:
        return {
            "n_identifiers": 0,
            "avg_identifier_length": 0.0,
            "avg_tokens_per_identifier": 0.0,
            "vocab_size": 0,
            "vocab_diversity": 0.0,
            "pct_snake_case": 0.0,
            "pct_camel_case": 0.0,
            "pct_pascal_case": 0.0
        }
    
    n = len(identifiers)
    vocab = set()
    total_chars = 0
    total_tokens = 0
    
    snake = 0
    camel = 0
    pascal = 0
    
    for row in identifiers:
        name = row["name"]
        conv = row["convention"]
        
        total_chars += row["length"]
        
        tokens = _tokenize(name)
        total_tokens += row["n_tokens"]
        vocab.update(tokens)
        
        if conv == "snake_case": snake += 1
        elif conv == "camelCase": camel += 1
        elif conv == "PascalCase": pascal += 1
        
    return {
        "n_identifiers": n,
        "avg_identifier_length": total_chars / n,
        "avg_tokens_per_identifier": total_tokens / n,
        "vocab_size": len(vocab),
        "vocab_diversity": len(vocab) / total_tokens if total_tokens > 0 else 0.0,
        "pct_snake_case": snake / n,
        "pct_camel_case": camel / n,
        "pct_pascal_case": pascal / n
    }

def build_file_identifier_dataset(xml_by_file: Dict[str, str], parser: str = "dom") -> List[Dict[str, Any]]:
    """Build file-level dataset rows from {file_path: xml_str}.

    Parameters:
    - xml_by_file: dict mapping file paths to srcML XML strings
    - parser: either 'dom' or 'sax' (default 'dom')
    
    Returns:
    - List of dicts, one per file, with keys:
      - file_path (str)
      - n_identifiers (int)
      - avg_identifier_length (float)
      - ... (all metrics from aggregate_identifier_features)
    
    Behavior:
    - Raise ValueError if parser is not 'dom' or 'sax'
    - Process files in sorted order (for reproducibility)
    - For each file: extract identifiers → aggregate → append to output
    
    Examples:
    >>> xml_map = {'a.py': '<unit>...</unit>', 'b.py': '<unit>...</unit>'}
    >>> dataset = build_file_identifier_dataset(xml_map, parser='dom')
    >>> len(dataset)
    2
    >>> dataset[0]['file_path']
    'a.py'
    
    Implementation hints:
    - Normalize parser string: parser.lower().strip()
    - Use sorted(xml_by_file.keys()) for deterministic iteration
    - Call extract_identifiers_dom or extract_identifiers_sax based on parser choice
    - Merge file_path with aggregate dict: {'file_path': path, **agg}
    """
    parser = parser.lower().strip()
    if parser not in ['dom', 'sax']:
        raise ValueError(f"Unsupported parser: {parser}. Must be 'dom' or 'sax'")
        
    dataset = []
    
    for file_path in sorted(xml_by_file.keys()):
        content = xml_by_file[file_path]
        
        if not content.strip().startswith('<?xml') and not content.strip().startswith('<unit'):
            content = run_srcml_on_text(content, filename_hint=file_path)
            
        if parser == 'dom':
            identifiers = extract_identifiers_dom(content)
        else:
            raise NotImplementedError("SAX parsing not implemented.")
            
        agg = aggregate_identifier_features(identifiers)
        dataset.append({"file_path": file_path, **agg})
        
    return dataset


def export_dataset_to_csv(repo_path: str, commit_hash: str = "HEAD", output_csv: str = "identifier_dataset.csv"):
    print(f"Building identifier dataset for {repo_path} at {commit_hash}...")
    repo = Repo(repo_path)
    
    supported_extensions = ('.c', '.cpp', '.cxx', '.cs', '.java') 
    target_commit = repo.commit(commit_hash)
    file_paths = [item.path for item in target_commit.tree.traverse() 
                  if item.type == 'blob' and item.path.endswith(supported_extensions)]
    
    if not file_paths:
        print("No supported files found for srcML analysis.")
        return

    print(f"Found {len(file_paths)} supported files. Running srcML...")
    
    xml_by_file = {}
    for path in file_paths:
        try:
            xml_str = run_srcml_on_repo_file(repo_path, path, commit=commit_hash)
            xml_by_file[path] = xml_str
        except Exception as e:
            print(f"Warning: Failed to parse {path} - {e}")

    print("Aggregating features using build_file_identifier_dataset...")
    dataset = build_file_identifier_dataset(xml_by_file, parser="dom")

    if dataset:
        os.makedirs("output", exist_ok=True)
        out_path = os.path.join("output", output_csv)
        
        headers = list(dataset[0].keys())
        
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(dataset)
            
        print(f"Success! Wrote dataset for {len(dataset)} files to {out_path}")
    else:
        print("No dataset could be generated.")