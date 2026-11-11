"""Entry point. Phase 2 implements --mode discover; full/resume/update come later."""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
import time
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table

from config.logging_config import setup_logging
from config.settings import load_settings
from database.connection import init_db, make_engine
from database.repository import Repository
from discovery.categories import discover_categories
from discovery.products import crawl_category, merge_unique
from exports.json_exporter import export_json, verify
from pipeline.scraper_pipeline import build_index, download_all, ingest, load_discovery
from scraper.http_client import AccessBlocked, HttpClient, RobotsDisallowed

log = logging.getLogger("main")
console = Console()


def run_discover(args, settings) -> int:
    client = HttpClient(settings)
    started = time.time()
    try:
        plan = discover_categories(client, settings)
        targets = [args.only] if args.only else plan.included
        if args.pages:
            settings = dataclasses.replace(settings, max_pages_per_category=args.pages)
        results = []
        for slug in targets:
            results.append(crawl_category(client, settings, slug))
    except (AccessBlocked, RobotsDisallowed) as exc:
        console.print(f"[bold red]STOPPED:[/bold red] {exc}")
        log.error("stopped: %s", exc)
        return 2

    unique = merge_unique(results)
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "categories_included": plan.included,
        "categories_skipped": plan.skipped,
        "per_category": [
            {"slug": r.slug, "pages": r.pages_fetched, "total_pages": r.total_pages_reported,
             "items": r.listing_items, "errors": r.errors} for r in results
        ],
        "unique_products": len(unique),
        "products": [p.model_dump(exclude={"description_raw"}) for p in unique.values()],
    }
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path = settings.data_dir / "discovery.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    table = Table(title="Discovery summary")
    table.add_column("Category"); table.add_column("Pages", justify="right")
    table.add_column("Items", justify="right"); table.add_column("Errors")
    for r in results:
        table.add_row(r.slug, str(r.pages_fetched), str(r.listing_items), "; ".join(r.errors) or "-")
    console.print(table)
    console.print(f"Skipped (not eyewear): {', '.join(plan.skipped) or '-'}")
    console.print(f"Unique products: [bold]{len(unique)}[/bold]  | requests: {client.request_count}"
                  f"  | {time.time() - started:.0f}s")
    console.print(f"Saved {path}")
    return 0


def open_repo(settings) -> Repository:
    return Repository(init_db(make_engine(settings.data_dir / "dukpion.db")))


def print_stats(repo: Repository) -> None:
    st = repo.stats()
    console.print(f"Database: {st['products']} products, {st['images']} images "
                  f"{st['by_status']} | duplicates: {st['duplicate_images']} | "
                  f"products without description: {st['products_without_description']}")


def run_full(args, settings) -> int:
    path = settings.data_dir / "discovery.json"
    if not path.exists():
        console.print("Run --mode discover first.")
        return 1
    repo = open_repo(settings)
    records = load_discovery(path)
    console.print(f"Ingest: {dict(ingest(repo, records))}")
    ids = repo.product_ids()
    if args.limit:
        ids = ids[: args.limit]
    client, index = HttpClient(settings), build_index(repo)
    from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn
    try:
        with Progress(TextColumn("{task.description}"), BarColumn(), TextColumn("{task.completed}/{task.total}"),
                      TimeRemainingColumn(), console=console) as prog:
            task = prog.add_task("Downloading images", total=len(ids))
            counts = download_all(client, settings, repo, index, ids, args.retry_failed,
                                  on_product=lambda pid: prog.advance(task))
    except (AccessBlocked, RobotsDisallowed) as exc:
        console.print(f"[bold red]STOPPED:[/bold red] {exc}\nProgress is saved; fix the cause and rerun.")
        print_stats(repo)
        return 2
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted. Progress is saved; rerun the same command to continue.[/yellow]")
        print_stats(repo)
        return 130
    console.print(f"This run: {dict(counts)} | requests: {client.request_count}")
    print_stats(repo)
    return 0


def run_export(args, settings) -> int:
    repo = open_repo(settings)
    out = settings.data_dir / "products.json"
    n = export_json(repo, out, args.downloaded_only)
    console.print(f"Exported {n} products to {out}")
    problems = verify(repo, settings.data_dir, out, args.downloaded_only)
    if problems:
        console.print(f"[bold red]{len(problems)} consistency problems[/bold red]")
        for p in problems[:25]:
            console.print(" -", p)
        return 3
    console.print("[green]JSON, database and image files are consistent.[/green]")
    print_stats(repo)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Dukpion eyewear image/description scraper")
    ap.add_argument("--mode", choices=["discover", "full", "export", "resume", "update"], required=True)
    ap.add_argument("--only", help="discover only this category slug (testing)")
    ap.add_argument("--limit", type=int, help="process only the first N products (testing)")
    ap.add_argument("--retry-failed", action="store_true", help="also retry images that returned 404/410")
    ap.add_argument("--downloaded-only", action="store_true", help="export only successfully downloaded images")
    ap.add_argument("--pages", type=int, help="max pages per category (testing)")
    args = ap.parse_args()
    settings = load_settings()
    setup_logging(settings.log_dir)
    if args.mode == "export":   # no network use, no contact email needed
        return run_export(args, settings)
    if settings.has_placeholder_contact:
        console.print("[yellow]Set DUKPION_USER_AGENT with your real contact email in .env first.[/yellow]")
        return 1
    if args.mode == "discover":
        return run_discover(args, settings)
    if args.mode == "full":
        return run_full(args, settings)
    console.print(f"Mode '{args.mode}' arrives in Phase 6.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
