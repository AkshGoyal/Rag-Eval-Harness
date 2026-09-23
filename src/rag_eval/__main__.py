"""Command line entry point: ``python -m rag_eval <command>``."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from rag_eval.dataset.ingest import ingest_cuad
from rag_eval.dataset.loader import load_dataset
from rag_eval.errors import RagEvalError
from rag_eval.llm.catalog import fetch_catalog, fetch_embedding_catalog
from rag_eval.llm.client import API_KEY_VARIABLE, OPENROUTER_BASE_URL
from rag_eval.llm.smoke import run_smoke_test
from rag_eval.llm.transport import HttpTransport
from rag_eval.testset.build import build_testset, write_testset
from rag_eval.testset.templates import load_templates


def build_parser() -> argparse.ArgumentParser:
    """Define the command line surface."""
    parser = argparse.ArgumentParser(prog="rag_eval", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="download and normalise the corpus")
    ingest.add_argument(
        "--out",
        type=Path,
        default=Path("data/cuad/v1"),
        help="directory to write the dataset into (default: data/cuad/v1)",
    )

    verify = commands.add_parser("verify", help="check an ingested dataset is unchanged")
    verify.add_argument("--dataset", type=Path, default=Path("data/cuad/v1"))

    testset = commands.add_parser("build-testset", help="select test cases from the corpus")
    testset.add_argument("--dataset", type=Path, default=Path("data/cuad/v1"))
    testset.add_argument("--templates", type=Path, default=Path("testset/templates.yaml"))
    testset.add_argument("--out", type=Path, default=Path("testset"))
    testset.add_argument("--name", default="seed-v1")

    models = commands.add_parser("models", help="list models the gateway offers, with prices")
    models.add_argument("--search", default="", help="only show models whose id contains this")
    models.add_argument("--free", action="store_true", help="only show models that cost nothing")
    models.add_argument("--limit", type=int, default=40)

    smoke = commands.add_parser("check-models", help="make two tiny calls to prove the setup works")
    smoke.add_argument("--chat-model", default="meta-llama/llama-3.1-8b-instruct")
    smoke.add_argument("--embedding-model", default="openai/text-embedding-3-small")
    smoke.add_argument("--provider", default=None, help="pin to one upstream provider")
    smoke.add_argument("--cache", type=Path, default=Path(".cache/llm"))
    smoke.add_argument(
        "--fresh",
        action="store_true",
        help="use an empty cache, so both calls really reach the gateway",
    )

    return parser


def _money(usd: float) -> str:
    """Show a cost with enough precision to see it. Single calls cost millionths of a dollar."""
    return f"${usd:.8f}" if usd < 0.01 else f"${usd:.4f}"


def _api_key() -> str | None:
    """Read the gateway key from the environment, or from a local .env file.

    Read at call time rather than at import, so that importing this package on a
    machine with no credentials still works.
    """
    key = os.environ.get(API_KEY_VARIABLE)
    if key:
        return key
    env_file = Path(".env")
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == API_KEY_VARIABLE and value.strip():
                return value.strip().strip("\"'")
    return None


def main(argv: list[str] | None = None) -> int:
    """Run a command and return a process exit code."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "ingest":
            manifest = ingest_cuad(args.out)
            print(f"Ingested {manifest.name} {manifest.version} into {args.out}")
            print(f"  contracts    {manifest.contract_count:,}")
            print(
                f"  labels       {manifest.label_count:,} "
                f"({manifest.present_label_count:,} present, "
                f"{manifest.label_count - manifest.present_label_count:,} absent)"
            )
            print(f"  categories   {manifest.category_count}")
            print(f"  fingerprint  {manifest.content_hash}")
        elif args.command == "models":
            transport = HttpTransport()
            chat_catalog = fetch_catalog(
                transport, base_url=OPENROUTER_BASE_URL, api_key=_api_key()
            )
            embedding_catalog, note = fetch_embedding_catalog(
                transport, base_url=OPENROUTER_BASE_URL, api_key=_api_key()
            )
            catalog = chat_catalog + embedding_catalog
            shown = [
                model
                for model in catalog
                if args.search.lower() in model.model_id.lower()
                and (not args.free or model.is_free)
            ]
            shown.sort(key=lambda model: (model.price.input_per_million, model.model_id))
            print(f"{len(shown)} of {len(catalog)} models match\n")
            print(f"{'model':<52} {'$/M in':>9} {'$/M out':>9} {'context':>9}")
            for model in shown[: args.limit]:
                print(
                    f"{model.model_id:<52} {model.price.input_per_million:>9.4f} "
                    f"{model.price.output_per_million:>9.4f} {model.context_length:>9,}"
                )
            if len(shown) > args.limit:
                print(f"\n... and {len(shown) - args.limit} more; narrow with --search")
            if note:
                print(f"\nNote: {note}.")
                print("Embedding prices then come from configs/prices.yaml.")

        elif args.command == "check-models":
            cache_dir = args.cache
            if args.fresh:
                cache_dir = Path(tempfile.mkdtemp(prefix="rag-eval-smoke-"))
            result = run_smoke_test(
                HttpTransport(),
                base_url=OPENROUTER_BASE_URL,
                chat_model=args.chat_model,
                embedding_model=args.embedding_model,
                cache_dir=cache_dir,
                api_key=_api_key(),
                provider=args.provider,
            )
            for label, record in (
                ("Chat", result.chat_record),
                ("Embedding", result.embedding_record),
            ):
                print(label)
                print(f"  model       {record.model}")
                cached = "yes - no network call, no cost" if record.cache_hit else "no - real call"
                print(f"  from cache  {cached}")
                print(f"  served by   {record.provider_served or 'not reported'}")
                print(f"  tokens      {record.usage}")
                print(
                    f"  cost        {_money(record.cost_usd)}"
                    f"{'' if record.cost_known else '  (unknown: no usage reported)'}"
                )
                print(f"  attempts    {record.attempts}")
                if label == "Chat":
                    print(f"  truncated   {record.truncated}")
                    print(f"  answer      {result.chat_text}")
                else:
                    print(f"  dimensions  {result.embedding_dimensions}")
                print()
            print(f"Total: {_money(result.total_cost_usd)}")
            if result.catalogue_note:
                print(
                    f"Note: {result.catalogue_note}; embedding price came from configs/prices.yaml."
                )
            if not args.fresh:
                print("Run again: both calls should say 'from cache: yes' and cost nothing.")

        elif args.command == "build-testset":
            dataset = load_dataset(args.dataset, verify_files=False)
            templates = load_templates(args.templates)
            cases, built = build_testset(dataset, templates, name=args.name)
            write_testset(args.out, cases, built)
            print(f"Built {built.name}: {built.case_count} cases")
            for case_type, count in built.counts_by_type.items():
                print(f"  {count:3d}  {case_type}")
            print(f"  excluded for leakage  {built.excluded_for_leakage}")
            print(
                f"  highest overlap       {built.max_answer_overlap:.2f} "
                f"(threshold {built.overlap_threshold})"
            )
            print(f"  fingerprint           {built.content_hash}")
        else:
            dataset = load_dataset(args.dataset)
            print(f"{args.dataset} verified")
            print(f"  fingerprint  {dataset.manifest.content_hash}")
            print(f"  ingested     {dataset.manifest.created_at}")
    except RagEvalError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
