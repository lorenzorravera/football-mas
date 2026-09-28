"""
Pure-logic + DB-mocked checks for the documents / narrative-RAG layer (NO real DB,
NO LLM). Fast sanity of the building blocks added for the text layer:

  - _doc_scope_clause     (documents namespacing on doc_source)
  - query_documents       LEAKAGE GATE: as_of filter is present + NULL-excluding,
                          entity/doc_type filters, and the min_sim floor
  - _format_narrative     (synthesizer prompt block)
  - chunk_text            (Wikipedia ingester chunking)

The DB is faked: we monkeypatch _get_conn + _embed and capture the SQL/params that
query_documents would run, so we can assert the as_of gate exists WITHOUT a live DB.

Run:  cd Ethan/agent_v4 && python eval/tests/test_documents_rag.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class _FakeCursor:
    """Captures the last execute(sql, params); returns preset rows."""
    def __init__(self, rows):
        self._rows = rows
        self.captured = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.captured.append((sql, params))

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self.cursor_obj = _FakeCursor(rows)

    def cursor(self, *a, **k):
        return self.cursor_obj


def main() -> int:
    from memory import vector_store_pg as vs

    # ---- _doc_scope_clause: mirrors _scope_clause but on doc_source ---------
    sql, p = vs._doc_scope_clause("sess-9")
    assert sql == " AND session_id = %s" and p == ["sess-9"], (sql, p)
    sql, p = vs._doc_scope_clause(None)
    assert "doc_source IS NULL OR NOT (doc_source = ANY(%s))" in sql and p == [["eval_session"]], (sql, p)
    sql, p = vs._doc_scope_clause(None, exclude_sources=None)
    assert sql == "" and p == [], (sql, p)
    print("✓ _doc_scope_clause")

    # ---- query_documents LEAKAGE GATE (as_of) — DB mocked ------------------
    # Fake a single row that would clear the min_sim floor (distance 0.2 -> sim 0.9).
    row = {
        "doc_id": 1, "entity_type": "team", "entity_id": 5, "doc_type": "season_narrative",
        "as_of_date": None, "event_date": None, "source": "wiki", "text": "hello",
        "distance": 0.2,
    }
    orig_conn, orig_embed = vs._get_conn, vs._embed
    vs._embed = lambda t: [0.0] * vs.VECTOR_DIM
    try:
        # (a) as_of set -> SQL must gate on as_of_date and EXCLUDE NULL as_of_date
        fake = _FakeConn([row]); vs._get_conn = lambda: fake
        vs.query_documents("who wins?", as_of="2024-08-16")
        gate_sql, gate_params = fake.cursor_obj.captured[-1]
        assert "as_of_date IS NOT NULL AND as_of_date < %s" in gate_sql, gate_sql
        assert "2024-08-16" in gate_params, gate_params
        print("✓ query_documents as_of gate present + NULL-excluding (no leakage)")

        # (b) as_of None -> NO as_of gate (qualitative retrieval allows post-hoc text)
        fake = _FakeConn([row]); vs._get_conn = lambda: fake
        vs.query_documents("describe salah")
        open_sql, _ = fake.cursor_obj.captured[-1]
        assert "as_of_date <" not in open_sql, open_sql
        print("✓ query_documents ungated when as_of=None (qualitative)")

        # (c) entity + doc_type filters flow into the WHERE clause
        fake = _FakeConn([row]); vs._get_conn = lambda: fake
        vs.query_documents("x", entity_filter={"entity_type": "team", "entity_id": 5},
                           doc_types=["season_narrative"])
        f_sql, f_params = fake.cursor_obj.captured[-1]
        assert "entity_type = %s" in f_sql and "entity_id = %s" in f_sql and "doc_type = ANY(%s)" in f_sql, f_sql
        assert "team" in f_params and 5 in f_params and ["season_narrative"] in f_params, f_params
        print("✓ query_documents entity/doc_type filters")

        # (d) min_sim floor drops low-similarity rows
        low = dict(row, distance=1.9)  # sim ~0.05
        fake = _FakeConn([low]); vs._get_conn = lambda: fake
        out = vs.query_documents("x", min_sim=0.30)
        assert out == [], out
        fake = _FakeConn([row]); vs._get_conn = lambda: fake
        out = vs.query_documents("x", min_sim=0.30)
        assert len(out) == 1 and out[0]["similarity"] >= 0.30, out
        print("✓ query_documents min_sim floor")
    finally:
        vs._get_conn, vs._embed = orig_conn, orig_embed

    # ---- _format_narrative (synthesizer block) -----------------------------
    from agents.synthesizer import _format_narrative
    assert _format_narrative([]) == ""
    block = _format_narrative([{"source": "wiki", "text": "Arsenal had a strong season."}])
    assert "Arsenal had a strong season." in block and "wiki" in block
    print("✓ _format_narrative")

    # ---- chunk_text (Wikipedia ingester) -----------------------------------
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "data_prep"))
    from ingest_wikipedia import chunk_text
    text = "\n".join(f"Paragraph number {i} with some words." for i in range(20))
    chunks = chunk_text(text, max_chars=120)
    assert len(chunks) > 1 and all(len(c) <= 200 for c in chunks), [len(c) for c in chunks]
    assert chunk_text("") == []
    print("✓ chunk_text")

    print("\nAll documents-RAG logic checks passed ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
