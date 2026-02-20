from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import json

@dataclass(frozen=True)
class RetrievalUnit:
    uid: str
    symbol_type: str
    name: str
    qualified_name: str
    file_path: str
    signature: Optional[str]
    code: Optional[str]
    docstring: Optional[str]
    module: str

    depends_on: List[str]
    used_by: List[str]
    external_dependencies: List[str]

    def to_embedding_text(self) -> str:
        """
        Enhanced embedding text with full code and contextual information.
        
        Changes from original:
        - Removed metadata noise (file paths, symbol type labels)
        - Added dependency context (calls, called_by)
        - Removed code truncation (full code embedded)
        - Semantic prefix for context
        """
        sections = []
        
        # Semantic prefix (not metadata noise)
        sections.append(f"{self.symbol_type.capitalize()}: {self.qualified_name}")
        
        # Dependency context (architectural understanding)
        if self.depends_on:
            deps = ", ".join(self.depends_on[:5])  # Top 5 to avoid noise
            sections.append(f"Calls: {deps}")
        
        if self.used_by:
            users = ", ".join(self.used_by[:5])  # Top 5 to avoid noise
            sections.append(f"Called by: {users}")

        # Signature removed - not needed with full code

        # Semantic content (no truncation!)
        if self.docstring:
            sections.append(f"Documentation:\n{self.docstring}")

        if self.symbol_type in ("function", "class", "variable", "method") and self.code:
            sections.append(f"Code:\n{self.code}")  # Full code, no truncation

        return "\n\n".join(sections)

def _extract_signature(symbol: Dict[str, Any]) -> Optional[str]:
    """
    Best-effort signature extraction.
    Keeps it lightweight and language-agnostic.
    """
    if symbol["symbol_type"] in {"function", "method"}:
        name = symbol["name"]
        code = symbol.get("code")
        if not code:
            return None

        first_line = code.strip().splitlines()[0]
        return first_line

    if symbol["symbol_type"] == "class":
        return f"class {symbol['name']}"

    return None


def build_retrieval_units(
    symbols: List[Dict[str, Any]],
) -> List[RetrievalUnit]:
    """
    Converts raw symbol extraction output into canonical retrieval units.
    """

    units: List[RetrievalUnit] = []

    for symbol in symbols:
        unit = RetrievalUnit(
            uid=symbol["UID"],
            symbol_type=symbol["symbol_type"],
            name=symbol["name"],
            qualified_name=symbol.get("qualified_name"),
            file_path=symbol["file_path"],
            signature=_extract_signature(symbol),
            code=symbol.get("code"),
            docstring=symbol.get("docstring"),
            module = symbol.get("file_path").split('\\')[-1],
            
            depends_on=symbol.get("depends_on", []),
            used_by=symbol.get("used_by", []),
            external_dependencies=symbol.get("ext_dependencies", [])
        )
        units.append(unit)

    return units


def generate_retrievals(symbols_data):
    """Generate retrieval units from symbols data (dict or path)."""
    if isinstance(symbols_data, str):
        # Path to JSON file
        with open(symbols_data, "r", encoding="utf-8") as f:
            symbols_dict = json.load(f)
    else:
        # Already loaded dict
        symbols_dict = symbols_data
    
    raw_symbols = symbols_dict['symbols']
    retrieval_units = build_retrieval_units(raw_symbols)
    return retrieval_units

