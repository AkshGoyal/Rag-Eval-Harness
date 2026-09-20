"""Command line entry point: ``python -m rag_eval <command>``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rag_eval.dataset.ingest import ingest_cuad
from rag_eval.dataset.loader import load_dataset
from rag_eval.errors import RagEvalError
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

    return parser


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
