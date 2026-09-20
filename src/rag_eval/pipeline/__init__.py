"""The reference RAG pipeline: chunking, retrieval, and later generation."""

from rag_eval.pipeline.chunking import Chunk, chunk_text
from rag_eval.pipeline.corpus import build_chunks

__all__ = ["Chunk", "build_chunks", "chunk_text"]
