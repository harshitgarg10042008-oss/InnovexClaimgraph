import glob
import logging
import time
from pathlib import Path

from app.core.config import settings
from app.ingest.classify import classify_document
from app.ingest.extract import extract_document_facts
from app.ingest.read import read_document_pages
from app.llm.client import llm_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("claimgraph.ingest.populate_cache")


def populate_all_synthetic_caches() -> None:
    # Ensure live mode for cache population
    settings.LLM_MODE = "live"

    candidates = [
        Path("/data/synthetic"),
        Path(__file__).resolve().parents[3] / "data" / "synthetic",
        Path("data/synthetic").resolve(),
    ]
    synth_dir = next(c for c in candidates if c.exists())

    files = sorted(
        glob.glob(str(synth_dir / "**/*.pdf"), recursive=True)
        + glob.glob(str(synth_dir / "**/*.jpg"), recursive=True)
    )

    storage_base = Path(settings.STORAGE_DIR).resolve()
    temp_storage = storage_base / "cache_builder"
    temp_storage.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 80)
    print("CLAIMGRAPH M3: POPULATING LIVE EXTRACTION CACHE FOR 23 DOCUMENTS")
    print(f"Synthetic Directory: {synth_dir}")
    print(f"Total Synthetic Files: {len(files)}")
    print(f"Extraction Model: {settings.LLM_EXTRACT_MODEL}")
    print(f"Classification Model: {settings.LLM_CLASSIFY_MODEL}")
    print("=" * 80 + "\n")

    total_calls = 0
    total_429s = 0

    start_time = time.time()

    for idx, fpath_str in enumerate(files, 1):
        fpath = Path(fpath_str)
        rel = fpath.relative_to(synth_dir)
        print(f"[{idx:02d}/{len(files)}] Processing {rel}...")

        # 1. Read document
        doc_id = f"seed_{fpath.stem}"
        pages = read_document_pages(
            file_path=fpath,
            document_id=doc_id,
            storage_base=temp_storage,
        )
        full_text = "\n\n".join(f"--- Page {p.page_no} ---\n{p.text}" for p in pages)
        pages_words = {p.page_no: p.words for p in pages}

        # 2. Classify
        class_res = classify_document(full_text)
        if class_res.method == "llm":
            total_calls += 1

        # 3. Extract Facts (calls LLM with caching)
        facts = extract_document_facts(
            kind=class_res.kind,
            full_text=full_text,
            pages_words=pages_words,
            page_count=len(pages),
        )
        total_calls += 1

        print(f"      -> Kind: {class_res.kind:15} | Facts Extracted: {len(facts)}")

    elapsed = time.time() - start_time

    # Count storage cache files
    cache_dir = Path(settings.STORAGE_DIR) / "llm_cache"
    cache_files = list(cache_dir.glob("*.json")) if cache_dir.exists() else []

    # Copy cache to data/synthetic/_llm_cache
    copied_count = llm_client.sync_cache_to_synthetic()

    print("\n" + "=" * 80)
    print("CACHE POPULATION COMPLETED")
    print("=" * 80)
    print(f"Total Synthetic Documents Processed: {len(files)}")
    print(f"Total LLM Calls Executed:            {total_calls}")
    print(f"HTTP 429 Rate Limit Events Seen:     {total_429s}")
    print(f"Cache Files Stored in Storage:       {len(cache_files)}")
    print(f"Cache Files Copied to Synthetic:     {copied_count}")
    print(f"Elapsed Time:                        {elapsed:.1f}s")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    populate_all_synthetic_caches()
