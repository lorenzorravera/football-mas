"""
Wikipedia → `documents` (pgvector) ingestion — narrative text layer
===================================================================

OFFLINE, one-time ingestion. Pulls Wikipedia article text for a curated seed of
club-season narratives and player bios, chunks it, embeds each chunk with the
SAME all-MiniLM-L6-v2 model the memory layer uses, and stores it in the Aiven
`documents` table (see Ethan/agent_v4/memory/setup_documents.sql).

There are NO web calls at query time — the live agent only does an in-DB pgvector
lookup via memory.vector_store_pg.query_documents(). This script is the loader.

Leakage discipline: every ingested article is POST-HOC narrative, so each seed
row carries an explicit `as_of_date` in the (clearly post-event) future of what it
describes. That keeps it excluded from any pre-match forecast gate
(query_documents(as_of=kickoff) filters `as_of_date < kickoff`). Do NOT ingest
match previews here without a verified pre-kickoff timestamp.

Usage:
  # Ensure DATABASE_URI is set (reads Ethan/agent_v4/.env) and the table exists:
  #   psql $DATABASE_URI -f Ethan/agent_v4/memory/setup_documents.sql
  python Ethan/data_prep/ingest_wikipedia.py --dry-run   # fetch + preview, no writes
  python Ethan/data_prep/ingest_wikipedia.py             # fetch + write to Aiven

  # Options:
  #   --dry-run          fetch + chunk + print a summary, do NOT write to the DB
  #   --limit N          only process the first N seed entries
  #   --doc-source TAG   scope tag stored on each row (default 'live';
  #                      use e.g. 'eval_session' for throwaway loads)
  #   --max-chars N      target chunk size in characters (default 1200)
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

# Reuse the same .env the agent uses so we hit the same Aiven instance.
# override=True so the real URI in .env wins over any placeholder in the shell.
load_dotenv(Path(__file__).resolve().parents[1] / "agent_v4" / ".env", override=True)

# Import the store from the agent's memory package (single source of truth for the
# embedding model + insert shape).
_AGENT_V4 = Path(__file__).resolve().parents[1] / "agent_v4"
if str(_AGENT_V4) not in sys.path:
    sys.path.insert(0, str(_AGENT_V4))
from memory import vector_store_pg as vs  # noqa: E402


WIKI_API = "https://en.wikipedia.org/w/api.php"

# =============================================================================
# SEED SET — curated PoC corpus (extend freely). Each entry:
#   title       Wikipedia page title
#   entity_type 'team' | 'player' | 'season'
#   entity_name name to resolve to team_id / player_id (None -> entity_id NULL)
#   doc_type    'season_narrative' | 'player_bio'
#   event_date  what the text is ABOUT (ISO date or None for timeless bios)
#   as_of_date  when the text was publishable/known (POST-event; the leakage gate)
# =============================================================================

SEED_DOCS: list[dict] = [
    # --- 2024-25 club season narratives (post-season → as_of 2025-06-01) ---
    {"title": "2024–25 Liverpool F.C. season",          "entity_type": "team", "entity_name": "Liverpool",         "doc_type": "season_narrative", "event_date": "2025-05-25", "as_of_date": "2025-06-01"},
    {"title": "2024–25 Arsenal F.C. season",            "entity_type": "team", "entity_name": "Arsenal",           "doc_type": "season_narrative", "event_date": "2025-05-25", "as_of_date": "2025-06-01"},
    {"title": "2024–25 Manchester City F.C. season",    "entity_type": "team", "entity_name": "Manchester City",   "doc_type": "season_narrative", "event_date": "2025-05-25", "as_of_date": "2025-06-01"},
    {"title": "2024–25 Chelsea F.C. season",            "entity_type": "team", "entity_name": "Chelsea",           "doc_type": "season_narrative", "event_date": "2025-05-25", "as_of_date": "2025-06-01"},
    {"title": "2024–25 Manchester United F.C. season",  "entity_type": "team", "entity_name": "Manchester United", "doc_type": "season_narrative", "event_date": "2025-05-25", "as_of_date": "2025-06-01"},
    {"title": "2024–25 Tottenham Hotspur F.C. season",  "entity_type": "team", "entity_name": "Tottenham Hotspur", "doc_type": "season_narrative", "event_date": "2025-05-25", "as_of_date": "2025-06-01"},
    {"title": "2024–25 Newcastle United F.C. season",   "entity_type": "team", "entity_name": "Newcastle United",  "doc_type": "season_narrative", "event_date": "2025-05-25", "as_of_date": "2025-06-01"},
    {"title": "2024–25 Aston Villa F.C. season",        "entity_type": "team", "entity_name": "Aston Villa",       "doc_type": "season_narrative", "event_date": "2025-05-25", "as_of_date": "2025-06-01"},
    {"title": "2024–25 Premier League",                 "entity_type": "season", "entity_name": None,             "doc_type": "season_narrative", "event_date": "2025-05-25", "as_of_date": "2025-06-01"},

    # --- player bios (timeless-ish → as_of a recent fixed date, event_date None) ---
    {"title": "Mohamed Salah",   "entity_type": "player", "entity_name": "Mohamed Salah",   "doc_type": "player_bio", "event_date": None, "as_of_date": "2025-06-01"},
    {"title": "Erling Haaland",  "entity_type": "player", "entity_name": "Erling Haaland",  "doc_type": "player_bio", "event_date": None, "as_of_date": "2025-06-01"},
    {"title": "Bukayo Saka",     "entity_type": "player", "entity_name": "Bukayo Saka",     "doc_type": "player_bio", "event_date": None, "as_of_date": "2025-06-01"},
    {"title": "Cole Palmer",     "entity_type": "player", "entity_name": "Cole Palmer",     "doc_type": "player_bio", "event_date": None, "as_of_date": "2025-06-01"},
    {"title": "Virgil van Dijk", "entity_type": "player", "entity_name": "Virgil van Dijk", "doc_type": "player_bio", "event_date": None, "as_of_date": "2025-06-01"},
    {"title": "Bruno Fernandes", "entity_type": "player", "entity_name": "Bruno Fernandes", "doc_type": "player_bio", "event_date": None, "as_of_date": "2025-06-01"},
    {"title": "Declan Rice",     "entity_type": "player", "entity_name": "Declan Rice",     "doc_type": "player_bio", "event_date": None, "as_of_date": "2025-06-01"},
    {"title": "Son Heung-min",   "entity_type": "player", "entity_name": "Son Heung-min",   "doc_type": "player_bio", "event_date": None, "as_of_date": "2025-06-01"},
]


# =============================================================================
# Wikipedia fetch (stdlib urllib — no extra dependency)
# =============================================================================

def fetch_wikipedia_text(title: str) -> str | None:
    """Return the plain-text extract of a Wikipedia article, or None on miss."""
    params = {
        "action": "query",
        "format": "json",
        "prop": "extracts",
        "explaintext": "1",
        "redirects": "1",
        "titles": title,
    }
    url = WIKI_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "P13-football-agent/1.0 (research)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # network / parse — report and skip
        print(f"    ! fetch failed for {title!r}: {e}")
        return None
    pages = data.get("query", {}).get("pages", {})
    for _pid, page in pages.items():
        if "extract" in page and page["extract"].strip():
            return page["extract"]
    return None


def chunk_text(text: str, max_chars: int = 1200) -> list[str]:
    """Paragraph-aware chunking: pack paragraphs up to ~max_chars per chunk."""
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    chunks, buf = [], ""
    for p in paras:
        if buf and len(buf) + 1 + len(p) > max_chars:
            chunks.append(buf)
            buf = p
        else:
            buf = f"{buf}\n{p}" if buf else p
    if buf:
        chunks.append(buf)
    return chunks


# =============================================================================
# Entity resolution (best-effort; entity_id NULL if not found)
# =============================================================================

def resolve_entity_id(conn, entity_type: str, entity_name: str | None) -> int | None:
    """Look up team_id / player_id by name. Returns None if not resolvable."""
    if not entity_name or entity_type not in ("team", "player"):
        return None
    table, id_col, name_col = {
        "team":   ("teams", "team_id", "team_name"),
        "player": ("players", "player_id", "player_name"),
    }[entity_type]
    with conn.cursor() as cur:
        # exact, then case-insensitive contains
        cur.execute(f"SELECT {id_col} FROM {table} WHERE {name_col} = %s LIMIT 1", (entity_name,))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            f"SELECT {id_col} FROM {table} WHERE {name_col} ILIKE %s ORDER BY length({name_col}) LIMIT 1",
            (f"%{entity_name}%",),
        )
        row = cur.fetchone()
        return row[0] if row else None


# =============================================================================
# Main
# =============================================================================

def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest Wikipedia narrative into the documents table")
    ap.add_argument("--dry-run", action="store_true", help="fetch + chunk + print, do NOT write")
    ap.add_argument("--limit", type=int, default=None, help="process only the first N seed entries")
    ap.add_argument("--doc-source", default="live", help="scope tag stored on each row (default 'live')")
    ap.add_argument("--max-chars", type=int, default=1200, help="target chunk size in characters")
    args = ap.parse_args()

    seeds = SEED_DOCS[: args.limit] if args.limit else SEED_DOCS
    conn = None if args.dry_run else vs._get_conn()

    total_chunks = 0
    total_docs = 0
    print(f"Ingesting {len(seeds)} seed articles "
          f"({'DRY RUN — no writes' if args.dry_run else f'-> Aiven documents (doc_source={args.doc_source})'})\n")

    for i, seed in enumerate(seeds, 1):
        title = seed["title"]
        text = fetch_wikipedia_text(title)
        if not text:
            print(f"[{i:02d}/{len(seeds)}] {title!r}: NO EXTRACT — skipped")
            continue

        chunks = chunk_text(text, max_chars=args.max_chars)
        entity_id = None if args.dry_run else resolve_entity_id(conn, seed["entity_type"], seed.get("entity_name"))
        total_docs += 1
        total_chunks += len(chunks)

        eid_note = "(dry-run: id unresolved)" if args.dry_run else f"entity_id={entity_id}"
        print(f"[{i:02d}/{len(seeds)}] {title!r}: {len(text):,} chars -> {len(chunks)} chunks  "
              f"[{seed['entity_type']}/{seed['doc_type']}] {eid_note}")

        if args.dry_run:
            print(f"      preview: {chunks[0][:160].replace(chr(10), ' ')}...")
            continue

        source = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
        for chunk in chunks:
            vs.store_document(
                entity_type=seed["entity_type"],
                entity_id=entity_id,
                doc_type=seed["doc_type"],
                text=chunk,
                as_of_date=seed.get("as_of_date"),
                event_date=seed.get("event_date"),
                source=source,
                doc_source=args.doc_source,
            )

    print(f"\nDone. {total_docs} articles, {total_chunks} chunks "
          f"{'(dry run — nothing written)' if args.dry_run else 'written to documents'}.")
    if not args.dry_run:
        print(f"Row counts: {vs.memory_stats()}")


if __name__ == "__main__":
    main()
