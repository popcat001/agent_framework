# Web backend migrations

`init_db()` in `database.py` calls `Base.metadata.create_all()` on startup.
That call **only creates tables that do not yet exist**. It does not:

- add columns to existing tables
- add, drop, or widen constraints
- add or drop indexes
- change column types

This is fine for v1 of any new model (the table is created fresh), but means
**every subsequent schema change requires an explicit `ALTER TABLE`
migration**. Without one, the model code will silently drift from production
reality — the ORM will happily issue queries the DB cannot satisfy, and bugs
will only surface at runtime.

## Adding a migration

Place each migration as a numbered, timestamped SQL or Python script in this
directory. Example names:

```
2026_04_21_001_add_category_to_web_user_memory.sql
2026_05_15_002_add_last_used_at_index.sql
```

Keep migrations idempotent (`IF NOT EXISTS`, `IF EXISTS`) where reasonable so
re-running them against a partially-migrated DB is safe.

## Running

For now migrations are applied by hand by the team member doing the deploy:

```sh
psql "$DATABASE_URL" -f framework/web/backend/migrations/<filename>.sql
```

If migration volume grows, wire up Alembic and point its `script_location` at
this directory.

## Operational runbook — purge a user's memory

Right-to-be-forgotten requests and ops resets can be handled with a direct
DELETE; this is intentionally kept out of the product UI for v1 (see
plan_user_memory.md "Out of scope"):

```sql
DELETE FROM web_user_memory WHERE user_id = :uid;
```
