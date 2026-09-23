"""The `retrieve` command: score one configuration's retrieval against the test set.

Kept out of the command-line module so it can be tested without parsing arguments,
and so the command-line module stays a thin list of commands.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from rag_eval.config import RetrievalMethod, RunConfig, load_config
from rag_eval.dataset.loader import load_dataset
from rag_eval.errors import RagEvalError
from rag_eval.llm.factory import build_client
from rag_eval.llm.transport import HttpTransport, Transport
from rag_eval.metrics.retrieval import RetrievalReport, Searcher, evaluate_retrieval
from rag_eval.pipeline.chunking import Chunk
from rag_eval.pipeline.corpus import build_chunks
from rag_eval.retrieval.bm25 import BM25Index
from rag_eval.retrieval.dense import build_or_load, estimate_cost_usd, index_key
from rag_eval.testset.models import TestCase


def load_cases(path: Path) -> tuple[TestCase, ...]:
    """Read a test set, validating every case."""
    if not path.is_file():
        raise RagEvalError(f"{path} does not exist; run build-testset first")
    lines = path.read_text(encoding="utf-8").splitlines()
    return tuple(TestCase.model_validate(json.loads(line)) for line in lines if line.strip())


def run_retrieval(
    *,
    config_path: Path,
    dataset_path: Path,
    testset_path: Path,
    index_root: Path,
    cache_dir: Path,
    limit_usd: float,
    dry_run: bool,
    show_cases: bool,
    api_key: str | None,
    transport: Transport | None = None,
) -> int:
    """Build or load the configured retriever, score it, and print the report."""
    config = load_config(config_path)
    dataset = load_dataset(dataset_path, verify_files=False)
    cases = load_cases(testset_path)
    chunks = build_chunks(dataset, config.chunking)

    print(f"Configuration  {config.name}  ({config_path})")
    print(f"  method       {config.retrieval.method.value}")
    print(f"  chunks       {len(chunks):,} of {config.chunking.size:,} characters")
    print(f"  dataset      {dataset.manifest.content_hash[:16]}")
    print(f"  test set     {testset_path.name}, {len(cases)} cases")

    searcher: Searcher
    if config.retrieval.method is RetrievalMethod.BM25:
        started = time.monotonic()
        searcher = BM25Index(chunks)
        print(f"  index        keyword, built in {time.monotonic() - started:.1f}s, cost $0")
    else:
        searcher_or_none = _dense(
            config,
            chunks,
            dataset.manifest.content_hash,
            index_root=index_root,
            cache_dir=cache_dir,
            limit_usd=limit_usd,
            dry_run=dry_run,
            api_key=api_key,
            transport=transport or HttpTransport(),
        )
        if searcher_or_none is None:
            return 0
        searcher = searcher_or_none

    report = evaluate_retrieval(cases, searcher)
    _print_report(report, show_cases=show_cases)
    return 1 if report.errors else 0


def _dense(
    config: RunConfig,
    chunks: tuple[Chunk, ...],
    dataset_hash: str,
    *,
    index_root: Path,
    cache_dir: Path,
    limit_usd: float,
    dry_run: bool,
    api_key: str | None,
    transport: Transport,
) -> Searcher | None:
    """Estimate, then build or load the vector index. Returns None after a dry run."""
    priced = build_client(transport, cache_dir=cache_dir, limit_usd=limit_usd, api_key=api_key)
    price = priced.prices.get(config.embedding.model)
    key = index_key(dataset_hash, config.chunking, config.embedding)
    saved = (index_root / key[:16] / "vectors.npy").is_file()

    print(f"  embedding    {config.embedding.model}")
    if saved:
        print("  index        already built for this corpus, chunking and model - reusing it")
    elif price is not None:
        estimate = estimate_cost_usd(chunks, price.input_per_million)
        print(
            f"  estimate     ${estimate:.4f} to embed every chunk once "
            f"(limit ${limit_usd:.2f}); cached batches cost nothing"
        )
        if estimate > limit_usd:
            raise RagEvalError(
                f"the estimate ${estimate:.4f} exceeds the spending limit ${limit_usd:.2f}; "
                "raise --limit-usd deliberately if this is expected"
            )
    if dry_run:
        print("\nDry run: nothing was spent.")
        return None

    started = time.monotonic()

    def progress(done: int, total: int) -> None:
        if done == total or done % 20 == 0:
            print(f"  embedding    batch {done}/{total}", flush=True)

    index, build = build_or_load(
        chunks,
        client=priced.client,
        embedding=config.embedding,
        key=key,
        root=index_root,
        progress=None if saved else progress,
    )
    if not build.reused:
        print(
            f"  index        built in {time.monotonic() - started:.0f}s: {build.requests} requests "
            f"({build.cached_requests} from cache), {build.dimensions} dimensions, "
            f"cost ${build.cost_usd:.6f}, served by {', '.join(build.providers_served) or '?'}"
        )
    return index


def _print_report(report: RetrievalReport, *, show_cases: bool) -> None:
    ks = report.ks
    scored = len(report.results)
    print(
        f"\nScored {scored} answerable cases. Not scored: {report.not_scored} refusal cases "
        "(their correct answer is that there is nothing to find)."
    )
    if report.errors:
        print(f"ERRORS: {len(report.errors)} cases failed and score zero - listed below.")

    header = "  ".join(f"hit@{k:<2}" for k in ks)
    print(f"\n{'':<20} {'cases':>5}  {header}  span@5   MRR")
    rows = list(report.by_type.items())
    if report.overall is not None:
        rows.append(("OVERALL", report.overall))
    for name, group in rows:
        hits = "  ".join(f"{group.hit_at[k]:>5.0%}" for k in ks)
        span = group.span_recall_at.get(5, 0.0)
        print(f"{name:<20} {group.cases:>5}  {hits}  {span:>5.0%}  {group.mrr:>5.2f}")

    if show_cases or report.errors:
        print("\nPer case (rank of the first passage containing the answer; - means not found):")
        for result in report.results:
            if not show_cases and result.error is None:
                continue
            rank = "-" if result.first_hit_rank is None else str(result.first_hit_rank)
            detail = f"  ERROR {result.error}" if result.error else ""
            print(
                f"  {result.case_id}  rank {rank:>2}  {result.case_type:<18} "
                f"{result.question[:70]}{detail}"
            )
