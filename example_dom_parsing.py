"""
Example: DOM-based XML Parsing (without XPath)

DOM (Document Object Model) loads the entire XML document into memory as a tree
structure. You can then traverse this tree using methods like iter(), find(),
findall(), etc. This approach provides random access to any element.

This example demonstrates:
- Parsing srcML output using DOM (ElementTree)
- Manually traversing the tree without XPath
- Extracting function information using iteration
"""

import sys
from pathlib import Path
import xml.etree.ElementTree as ET

from src.srcml_runner import run_srcml_on_text


def strip_namespace(tag: str) -> str:
    """Remove namespace prefix from tag."""
    if '}' in tag:
        return tag.split('}', 1)[1]
    return tag


def parse_with_dom(srcml_xml: str):
    """Parse srcML XML using DOM and extract function information."""
    root = ET.fromstring(srcml_xml)
    
    function_count = 0
    function_names = []
    
    # Approach 1: Using iter() to find all elements with 'function' tag
    # This traverses the entire tree
    for elem in root.iter():
        tag = strip_namespace(elem.tag)
        if tag == 'function':
            function_count += 1
            
            # Find the function name by looking for the first 'name' child
            # We need to be careful to get the function name, not parameter names
            for child in elem:
                child_tag = strip_namespace(child.tag)
                if child_tag == 'name':
                    # Extract text content from the name element
                    name_text = ''.join(child.itertext()).strip()
                    if name_text:
                        function_names.append(name_text)
                    break  # Only take the first name (function name)
    
    return function_count, function_names


def parse_with_dom_alternative(srcml_xml: str):
    """Alternative DOM approach using findall() with namespace."""
    root = ET.fromstring(srcml_xml)
    
    # Extract namespace from root tag
    namespace = {}
    if 'xmlns' in root.attrib:
        ns_uri = root.attrib['xmlns']
        namespace['src'] = ns_uri
    
    # Note: findall() only searches immediate children (not descendants)
    # So we'd need to use iter() or XPath for deep search
    # This shows the limitation of DOM without XPath
    
    function_count = 0
    function_names = []
    
    # Manually traverse to find all function elements
    def visit(element):
        nonlocal function_count
        tag = strip_namespace(element.tag)
        if tag == 'function':
            function_count += 1
            # Get first name element
            for child in element:
                if strip_namespace(child.tag) == 'name':
                    name_text = ''.join(child.itertext()).strip()
                    if name_text:
                        function_names.append(name_text)
                    break
        
        # Recurse into children
        for child in element:
            visit(child)
    
    visit(root)
    return function_count, function_names


def main():
    print("=" * 70)
    print("DOM (Document Object Model) XML Parsing Example - Without XPath")
    print("=" * 70)
    print()
    
    # Read the example Java file
    java_file = Path(__file__).resolve().parent / 'Calculator.java'
    with java_file.open('r', encoding='utf-8') as f:
        java_code = f.read()
    
    print("Input Java code:")
    print("-" * 70)
    print(java_code)
    print()
    
    # Convert to srcML
    print("Converting to srcML...")
    srcml_xml = run_srcml_on_text(java_code, filename_hint="Calculator.java")
    print("srcML conversion complete.")
    print()
    
    # Parse with DOM (approach 1)
    print("Parsing with DOM (using iter())...")
    count1, names1 = parse_with_dom(srcml_xml)
    
    print(f"Total functions found: {count1}")
    print(f"Function names: {', '.join(names1)}")
    print()
    
    # Parse with DOM (approach 2)
    print("Parsing with DOM (manual recursion)...")
    count2, names2 = parse_with_dom_alternative(srcml_xml)
    
    print(f"Total functions found: {count2}")
    print(f"Function names: {', '.join(names2)}")
    print()
    
    print("How DOM (without XPath) works:")
    print("- Loads entire XML document into memory as a tree")
    print("- Provides methods: iter(), find(), findall(), itertext()")
    print("- Can navigate forward and backward in the tree")
    print("- Must manually traverse/iterate to find elements")
    print("- More memory usage than SAX, but allows random access")
    print("- Best for: moderate-sized documents, need to access multiple parts")
    print()
    
    print("Limitations without XPath:")
    print("- Must write loops to find elements at any depth")
    print("- Cannot easily express complex queries (e.g., 'all functions in a class')")
    print("- More verbose code for nested or conditional searches")
    print()


if __name__ == "__main__":
    main()
