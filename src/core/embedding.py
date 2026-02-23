from typing import List, Dict, Any
from pathlib import Path
from dataclasses import asdict

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.callbacks import CallbackManagerForRetrieverRun


# -------------------------
# Document Conversion
# -------------------------

def retrieval_unit_to_document(unit) -> Document:
    """Convert a retrieval unit to a LangChain Document."""
    unit_dict = asdict(unit) if hasattr(unit, '__dataclass_fields__') else unit
    
    # Use the embedding text as page_content
    page_content = unit.to_embedding_text() if hasattr(unit, 'to_embedding_text') else str(unit)
    
    # Store all metadata
    metadata = {
        **unit_dict,
        "qualified_name": unit_dict.get("qualified_name", ""),
        "symbol_type": unit_dict.get("symbol_type", ""),
        "file_path": unit_dict.get("file_path", ""),
    }
    
    return Document(page_content=page_content, metadata=metadata)


# -------------------------
# Vector Store Management
# -------------------------

def load_or_create_index(
    retrieval_units,
    embedding_model_name: str,
    store_path: str,
    force_rebuild: bool = False
) -> tuple[FAISS, list]:
    """
    Load or create a FAISS vector store using LangChain.
    
    Returns:
        (FAISS vector store, metadata list)
    """
    store_path = Path(store_path)
    
    # Initialize embeddings - removed show_progress_bar from encode_kwargs
    # as it's handled internally by the model
    embeddings = HuggingFaceEmbeddings(
        model_name=embedding_model_name,
        model_kwargs={'device': 'cpu'},
        encode_kwargs={'normalize_embeddings': True, 'batch_size': 32}
    )
    
    # Try to load existing store
    if not force_rebuild and store_path.exists() and (store_path / "index.faiss").exists():
        try:
            print("Loading existing vector store")
            vectorstore = FAISS.load_local(
                str(store_path),
                embeddings,
                allow_dangerous_deserialization=True
            )
            
            # Load metadata separately
            import json
            metadata_path = store_path / "metadata.json"
            if metadata_path.exists():
                with metadata_path.open("r", encoding="utf-8") as f:
                    metadata = json.load(f)
            else:
                # Extract from vectorstore docstore
                metadata = [doc.metadata for doc in vectorstore.docstore._dict.values()]
            
            return vectorstore, metadata
            
        except Exception as e:
            print(f"Failed to load existing store: {e}")
            print("Building new vector store")
    else:
        print("Building new vector store")
    
    # Build new vector store
    documents = [retrieval_unit_to_document(unit) for unit in retrieval_units]
    metadata = [asdict(unit) if hasattr(unit, '__dataclass_fields__') else unit for unit in retrieval_units]
    
    vectorstore = FAISS.from_documents(documents, embeddings)
    
    # Save vector store
    store_path.mkdir(parents=True, exist_ok=True)
    vectorstore.save_local(str(store_path))
    
    # Save metadata separately for compatibility
    import json
    with (store_path / "metadata.json").open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    
    return vectorstore, metadata


# -------------------------
# Search Function (Backward Compatibility)
# -------------------------

def search(
    query: str,
    vectorstore: FAISS,
    metadata: list,
    EMBEDDING_MODEL_NAME: str = None,  # Not used, kept for compatibility
    k: int = 5,
) -> List[Dict[str, Any]]:
    """
    Search the vector store and return results in the original format.
    
    Args:
        query: Search query
        vectorstore: FAISS vectorstore (can also accept old index for compatibility)
        metadata: Metadata list
        EMBEDDING_MODEL_NAME: Not used, kept for backward compatibility
        k: Number of results
        
    Returns:
        List of dicts with 'score' and 'symbol' keys
    """
    # Handle both new FAISS vectorstore and old index
    if isinstance(vectorstore, FAISS):
        # New LangChain FAISS
        docs_and_scores = vectorstore.similarity_search_with_score(query, k=k)
        
        results = []
        for doc, score in docs_and_scores:
            results.append({
                "score": float(score),
                "symbol": doc.metadata,
            })
        return results
    else:
        # Fallback for old implementation (shouldn't happen after migration)
        raise ValueError("Old FAISS index format not supported. Please rebuild the index.")


# -------------------------
# Custom Scope-Based Retriever
# -------------------------

SCOPE_ELIGIBILITY = {
    "symbol": {"function", "class", "variable"},
    "module": {"module"},
    "system": {"module"},
}

RECALL_K_BY_SCOPE = {
    "symbol": 10,
    "module": 30,
    "system": 50,
}

FINAL_K_BY_SCOPE = {
    "symbol": 15,
    "module": 10,
    "system": 10,
}


class ScopeRetriever(BaseRetriever):
    """Custom retriever that implements scope-based filtering."""
    
    vectorstore: FAISS
    scope: str
    metadata: list
    
    class Config:
        arbitrary_types_allowed = True
    
    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun = None
    ) -> List[Document]:
        """Retrieve documents with scope-based filtering."""
        
        # 1. Broad recall
        recall_k = RECALL_K_BY_SCOPE.get(self.scope, 30)
        candidates = self.vectorstore.similarity_search_with_score(query, k=recall_k)
        
        # 2. Scope eligibility filter
        eligible_types = SCOPE_ELIGIBILITY.get(self.scope, set())
        eligible = [
            (doc, score) for doc, score in candidates
            if doc.metadata.get("symbol_type") in eligible_types
        ]
        
        if not eligible:
            return []
        
        # 3. Return top-k
        final_k = FINAL_K_BY_SCOPE.get(self.scope, 5)
        return [doc for doc, score in eligible[:final_k]]
