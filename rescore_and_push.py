"""
rescore_and_push.py
────────────────────────────────────────────────────────────────────────────────
Standalone script — run this once (or on a schedule) to:
  1. Pull every row from your Supabase `incidents` table
  2. Apply the custom risk formula from utils/risk_scorer.py
  3. Upsert the new severity + score columns back to Supabase

Usage
-----
    # Install deps first (if not already):
    pip install supabase pandas python-dotenv

    # Run:
    python rescore_and_push.py

    # Dry-run (print results, no DB write):
    python rescore_and_push.py --dry-run

    # Score a specific table:
    python rescore_and_push.py --table my_incidents_table

Environment / secrets
---------------------
Set these in a .env file (or your shell) OR in .streamlit/secrets.toml.
The script reads both.

    SUPABASE_URL=https://xxxx.supabase.co
    SUPABASE_KEY=your-service-role-key     ← use service_role, NOT anon, to allow UPDATE

────────────────────────────────────────────────────────────────────────────────
"""

import os
import sys
import argparse
import time
import pandas as pd
from supabase import create_client

# ── Try loading from .env (optional) ─────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass   # python-dotenv not installed — that's fine

# ── Try loading from .streamlit/secrets.toml (optional) ──────────────────────
def _load_streamlit_secrets():
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            return None, None

    secrets_path = os.path.join(".streamlit", "secrets.toml")
    if not os.path.exists(secrets_path):
        return None, None
    with open(secrets_path, "rb") as f:
        data = tomllib.load(f)
    sb = data.get("supabase", {})
    return sb.get("url"), sb.get("key")


def get_credentials():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        url, key = _load_streamlit_secrets()
    if not url or not key:
        print("❌  Could not find Supabase credentials.")
        print("    Set SUPABASE_URL and SUPABASE_KEY in .env or .streamlit/secrets.toml")
        sys.exit(1)
    return url, key


# ── Paginated fetch ───────────────────────────────────────────────────────────
def fetch_all(client, table: str, page_size: int = 1000) -> pd.DataFrame:
    all_rows, page = [], 0
    while True:
        start = page * page_size
        end   = start + page_size - 1
        resp  = client.table(table).select("*").range(start, end).execute()
        batch = resp.data or []
        all_rows.extend(batch)
        print(f"  Fetched page {page+1}: {len(batch)} rows")
        if len(batch) < page_size:
            break
        page += 1
    return pd.DataFrame(all_rows)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Rescore incidents and push to Supabase")
    parser.add_argument("--table",   default="incidents", help="Supabase table name (default: incidents)")
    parser.add_argument("--dry-run", action="store_true", help="Print scores without writing to DB")
    parser.add_argument("--id-col",  default="id",        help="Primary key column name (default: id)")
    parser.add_argument("--batch",   type=int, default=50, help="Upsert batch size (default: 50)")
    args = parser.parse_args()

    # ── Import scorer AFTER path is set ───────────────────────────────────────
    sys.path.insert(0, os.path.dirname(__file__))
    from utils.risk_scorer import score_dataframe, build_update_payload

    print(f"\n{'='*60}")
    print(f"  Flocks CSM — Risk Rescoring Engine")
    print(f"{'='*60}")
    print(f"  Table   : {args.table}")
    print(f"  Dry run : {args.dry_run}")
    print(f"  ID col  : {args.id_col}")
    print()

    url, key = get_credentials()
    client   = create_client(url, key)

    # ── 1. Fetch ───────────────────────────────────────────────────────────────
    print(f"[1/3] Fetching rows from '{args.table}'…")
    df = fetch_all(client, args.table)
    if df.empty:
        print("  ⚠️  No rows found. Exiting.")
        return
    print(f"  ✓  {len(df)} total rows loaded\n")

    # ── 2. Score ───────────────────────────────────────────────────────────────
    print("[2/3] Applying risk formula…")
    t0 = time.time()
    df_scored = score_dataframe(df)
    elapsed = time.time() - t0
    print(f"  ✓  Scored {len(df_scored)} rows in {elapsed:.2f}s\n")

    # Summary
    dist = df_scored["severity"].value_counts()
    print("  Severity distribution after rescoring:")
    for lvl in ["Critical", "High", "Medium", "Low"]:
        n   = dist.get(lvl, 0)
        pct = n / len(df_scored) * 100
        bar = "█" * int(pct / 3)
        print(f"    {lvl:<10} {bar:<35} {n:>5} ({pct:5.1f}%)")
    print()

    if args.dry_run:
        print("[DRY RUN] Sample of scored rows:")
        cols = [args.id_col, "severity", "risk_score", "sector_score",
                "country_score", "attack_type_score", "data_exposure_score", "attack_class"]
        show = [c for c in cols if c in df_scored.columns]
        print(df_scored[show].head(10).to_string(index=False))
        print("\n  Dry run complete — no changes written to Supabase.")
        return

    # ── 3. Upsert ──────────────────────────────────────────────────────────────
    if args.id_col not in df_scored.columns:
        print(f"❌  ID column '{args.id_col}' not found in data.")
        print(f"    Available columns: {list(df_scored.columns)}")
        sys.exit(1)

    print(f"[3/3] Upserting scored rows to Supabase (batch={args.batch})…")
    records = []
    for _, row in df_scored.iterrows():
        payload = build_update_payload(row)
        payload[args.id_col] = row[args.id_col]   # include PK for upsert
        records.append(payload)

    success, errors = 0, 0
    total_batches = (len(records) + args.batch - 1) // args.batch

    for i in range(0, len(records), args.batch):
        batch_num = i // args.batch + 1
        batch     = records[i : i + args.batch]
        try:
            client.table(args.table).upsert(batch, on_conflict=args.id_col).execute()
            success += len(batch)
            print(f"  Batch {batch_num}/{total_batches}: ✓ {len(batch)} rows upserted")
        except Exception as e:
            errors += len(batch)
            print(f"  Batch {batch_num}/{total_batches}: ✗ Error — {e}")

    print()
    print(f"  {'='*40}")
    print(f"  Done. {success} rows updated, {errors} errors.")
    print(f"  {'='*40}\n")

    if errors:
        print("  ⚠️  Some rows failed. This usually means:")
        print("     1. The columns (risk_score, sector_score, etc.) don't exist yet.")
        print("     2. You're using the anon key instead of service_role key.")
        print("     Run the SQL migration below in Supabase → SQL Editor:\n")
        print(_migration_sql(args.table))


def _migration_sql(table: str) -> str:
    return f"""
-- Run this ONCE in Supabase SQL Editor before pushing scores:
ALTER TABLE public.{table}
  ADD COLUMN IF NOT EXISTS risk_score          FLOAT,
  ADD COLUMN IF NOT EXISTS sector_score        FLOAT,
  ADD COLUMN IF NOT EXISTS country_score       FLOAT,
  ADD COLUMN IF NOT EXISTS attack_type_score   FLOAT,
  ADD COLUMN IF NOT EXISTS data_exposure_score FLOAT,
  ADD COLUMN IF NOT EXISTS attack_class        TEXT;

-- severity column likely exists already; if not:
-- ALTER TABLE public.{table} ADD COLUMN IF NOT EXISTS severity TEXT;
"""


if __name__ == "__main__":
    main()
