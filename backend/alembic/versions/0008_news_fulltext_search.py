"""Full-text search over the news corpus.

Revision ID: 0008
Revises: 0007

Retrieval for the AI assistant (and the news feed) matched with `title ILIKE '%q%'`, which
has no notion of relevance: it either matched a literal substring or it did not, and the
result was then ordered purely by recency. With 81k disclosures that means the twelve rows
handed to the model were "the twelve newest for this ticker", never "the twelve that answer
the question".

Design notes:

* No Vietnamese text-search configuration ships with PostgreSQL, so `simple` is used: it
  tokenises and lowercases without stemming. Vietnamese is largely non-inflecting, so the
  stemming loss is small; the real win is tokenisation plus ranking.
* `unaccent` lets "pha loang" match "pha loãng" - users type without diacritics constantly.
  It is not marked IMMUTABLE (it depends on a dictionary), so it cannot be used directly in
  a generated column or index; the standard workaround is a thin IMMUTABLE wrapper, which
  is safe here because the dictionary is fixed for the life of the database.
* The column is GENERATED, so the ingestion path needs no change and can never forget to
  keep the index in sync.
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION f_unaccent(text)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE PARALLEL SAFE STRICT
        AS $$ SELECT public.unaccent('public.unaccent', $1) $$
        """
    )
    # Title carries the signal; `summary_html` is raw HTML whose tags would pollute the
    # lexeme set, and category is a short controlled vocabulary worth matching on.
    op.execute(
        """
        ALTER TABLE external_news
        ADD COLUMN IF NOT EXISTS search_tsv tsvector
        GENERATED ALWAYS AS (
            to_tsvector(
                'simple',
                f_unaccent(coalesce(title, '') || ' ' || coalesce(category, ''))
            )
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_external_news_search_tsv "
        "ON external_news USING GIN (search_tsv)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_external_news_search_tsv")
    op.execute("ALTER TABLE external_news DROP COLUMN IF EXISTS search_tsv")
    op.execute("DROP FUNCTION IF EXISTS f_unaccent(text)")
    # `unaccent` is left installed: other objects may come to depend on it, and dropping an
    # extension is not something a schema downgrade should do on its own.
