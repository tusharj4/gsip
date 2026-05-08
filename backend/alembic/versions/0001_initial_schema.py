"""Initial PostGIS schema — all 6 core tables.

Revision ID: 0001
Revises:
Create Date: 2026-05-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable PostGIS extensions (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis_topology")
    # pgRouting is optional — only available when using a pgrouting-enabled image
    op.execute("""
        DO $$
        BEGIN
            CREATE EXTENSION IF NOT EXISTS pgrouting;
        EXCEPTION WHEN OTHERS THEN
            RAISE WARNING 'pgRouting not available (routing features disabled): %', SQLERRM;
        END $$
    """)

    # ── updated_at trigger function (shared by multiple tables) ───────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
        $$ LANGUAGE plpgsql
    """)

    # ── gis_layers ───────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE gis_layers (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name            VARCHAR(255) NOT NULL,
            slug            VARCHAR(255) UNIQUE NOT NULL,
            category        VARCHAR(100) NOT NULL,
            ministry_owner  VARCHAR(255),
            status          VARCHAR(50)  NOT NULL DEFAULT 'draft',
            source_url      TEXT,
            last_synced_at  TIMESTAMPTZ,
            metadata        JSONB        NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_gis_layers_category ON gis_layers(category)")
    op.execute("CREATE INDEX idx_gis_layers_status   ON gis_layers(status)")
    op.execute("""
        CREATE TRIGGER trg_gis_layers_updated_at
        BEFORE UPDATE ON gis_layers
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
    """)

    # ── layer_features ────────────────────────────────────────────────────────
    # geometry() is a PostGIS type — must be declared via raw DDL, not SQLAlchemy
    op.execute("""
        CREATE TABLE layer_features (
            id          BIGSERIAL PRIMARY KEY,
            layer_id    UUID        NOT NULL REFERENCES gis_layers(id) ON DELETE CASCADE,
            geom        geometry(Geometry, 4326) NOT NULL,
            properties  JSONB       NOT NULL DEFAULT '{}',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_layer_features_geom     ON layer_features USING GIST(geom)")
    op.execute("CREATE INDEX idx_layer_features_layer_id ON layer_features(layer_id)")

    # ── projects ──────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE projects (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name            VARCHAR(500)   NOT NULL,
            ministry        VARCHAR(255),
            project_type    VARCHAR(100),
            status          VARCHAR(50)    NOT NULL DEFAULT 'draft',
            corridor_geom   geometry(LineString, 4326),
            buffer_m        INTEGER        NOT NULL DEFAULT 500,
            cost_crore      NUMERIC(15, 2),
            metadata        JSONB          NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_projects_corridor ON projects USING GIST(corridor_geom)")
    op.execute("""
        CREATE TRIGGER trg_projects_updated_at
        BEFORE UPDATE ON projects
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
    """)

    # ── conflict_reports ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE conflict_reports (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id      UUID        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            layer_id        UUID        REFERENCES gis_layers(id),
            conflict_geom   geometry(Geometry, 4326),
            conflict_type   VARCHAR(100),
            severity        VARCHAR(20),
            area_sqm        NUMERIC(20, 4),
            description     TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_conflicts_project ON conflict_reports(project_id)")
    op.execute("CREATE INDEX idx_conflicts_geom    ON conflict_reports USING GIST(conflict_geom)")

    # ── gap_analyses ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE gap_analyses (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            analysis_type   VARCHAR(100),
            geography       geometry(Polygon, 4326),
            population      INTEGER,
            required_count  INTEGER,
            existing_count  INTEGER,
            gap_count       INTEGER,
            uncovered_geom  geometry(MultiPolygon, 4326),
            candidate_sites JSONB,
            parameters      JSONB NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_gaps_geography ON gap_analyses USING GIST(geography)")

    # ── audit_log ─────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE audit_log (
            id          BIGSERIAL PRIMARY KEY,
            entity_type VARCHAR(100),
            entity_id   UUID,
            action      VARCHAR(50),
            actor_id    UUID,
            actor_role  VARCHAR(50),
            notes       TEXT,
            diff        JSONB,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_audit_log_entity ON audit_log(entity_type, entity_id)")
    op.execute("CREATE INDEX idx_audit_log_actor  ON audit_log(actor_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE")
    op.execute("DROP TABLE IF EXISTS gap_analyses CASCADE")
    op.execute("DROP TABLE IF EXISTS conflict_reports CASCADE")
    op.execute("DROP TABLE IF EXISTS projects CASCADE")
    op.execute("DROP TABLE IF EXISTS layer_features CASCADE")
    op.execute("DROP TABLE IF EXISTS gis_layers CASCADE")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column CASCADE")
    op.execute("DROP EXTENSION IF EXISTS pgrouting CASCADE")
    op.execute("DROP EXTENSION IF EXISTS postgis_topology CASCADE")
    op.execute("DROP EXTENSION IF EXISTS postgis CASCADE")
