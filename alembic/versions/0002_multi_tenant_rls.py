"""Add organizations, tenant_id columns, and RLS policies.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])

    op.create_table(
        "org_memberships",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "org_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'admin'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "role IN ('admin', 'editor', 'viewer')",
            name="ck_org_memberships_role_valid",
        ),
        sa.UniqueConstraint("org_id", "user_id", name="uq_org_memberships_org_user"),
    )
    op.create_index("ix_org_memberships_user", "org_memberships", ["user_id"])

    op.execute(
        """
        INSERT INTO organizations (id, name, slug)
        SELECT gen_random_uuid(),
               split_part(email, '@', 1) || '''s Workspace',
               'user-' || id::text
        FROM users
        """
    )
    op.execute(
        """
        INSERT INTO org_memberships (org_id, user_id, role)
        SELECT organizations.id, users.id, 'admin'
        FROM users
        JOIN organizations ON organizations.slug = 'user-' || users.id::text
        """
    )

    op.add_column("documents", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.add_column("chunks", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("tenant_id", sa.Uuid(), nullable=True))

    op.execute(
        """
        UPDATE documents
        SET tenant_id = organizations.id
        FROM organizations
        WHERE organizations.slug = 'user-' || documents.user_id::text
        """
    )
    op.execute(
        """
        UPDATE chunks
        SET tenant_id = documents.tenant_id
        FROM documents
        WHERE documents.id = chunks.document_id
        """
    )
    op.execute(
        """
        UPDATE ingestion_jobs
        SET tenant_id = documents.tenant_id
        FROM documents
        WHERE documents.id = ingestion_jobs.document_id
        """
    )

    op.alter_column("documents", "tenant_id", nullable=False)
    op.alter_column("chunks", "tenant_id", nullable=False)
    op.alter_column("ingestion_jobs", "tenant_id", nullable=False)

    op.create_foreign_key(
        "fk_documents_tenant_id_organizations",
        "documents",
        "organizations",
        ["tenant_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_chunks_tenant_id_organizations",
        "chunks",
        "organizations",
        ["tenant_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_ingestion_jobs_tenant_id_organizations",
        "ingestion_jobs",
        "organizations",
        ["tenant_id"],
        ["id"],
    )

    op.drop_constraint("uq_documents_user_content", "documents", type_="unique")
    op.drop_constraint("uq_jobs_user_idempotency", "ingestion_jobs", type_="unique")
    op.create_unique_constraint(
        "uq_documents_tenant_content",
        "documents",
        ["tenant_id", "content_hash"],
    )
    op.create_unique_constraint(
        "uq_jobs_tenant_idempotency",
        "ingestion_jobs",
        ["tenant_id", "idempotency_key"],
    )

    op.execute(
        "CREATE INDEX ix_documents_tenant_active "
        "ON documents (tenant_id, created_at DESC) "
        "WHERE deleted_at IS NULL"
    )
    op.create_index("ix_chunks_tenant_id", "chunks", ["tenant_id"])

    _enable_rls("documents")
    _enable_rls("chunks")
    _enable_rls("ingestion_jobs")


def downgrade() -> None:
    _disable_rls("ingestion_jobs")
    _disable_rls("chunks")
    _disable_rls("documents")

    op.drop_index("ix_chunks_tenant_id", table_name="chunks")
    op.drop_index("ix_documents_tenant_active", table_name="documents")

    op.drop_constraint("uq_jobs_tenant_idempotency", "ingestion_jobs", type_="unique")
    op.drop_constraint("uq_documents_tenant_content", "documents", type_="unique")
    op.create_unique_constraint(
        "uq_jobs_user_idempotency",
        "ingestion_jobs",
        ["user_id", "idempotency_key"],
    )
    op.create_unique_constraint(
        "uq_documents_user_content",
        "documents",
        ["user_id", "content_hash"],
    )

    op.drop_constraint(
        "fk_ingestion_jobs_tenant_id_organizations",
        "ingestion_jobs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_chunks_tenant_id_organizations", "chunks", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_documents_tenant_id_organizations", "documents", type_="foreignkey"
    )

    op.drop_column("ingestion_jobs", "tenant_id")
    op.drop_column("chunks", "tenant_id")
    op.drop_column("documents", "tenant_id")

    op.drop_index("ix_org_memberships_user", table_name="org_memberships")
    op.drop_table("org_memberships")
    op.drop_index("ix_organizations_slug", table_name="organizations")
    op.drop_table("organizations")


def _enable_rls(table_name: str) -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table_name}
        USING (
            tenant_id = nullif(current_setting('app.current_tenant', true), '')::uuid
        )
        WITH CHECK (
            tenant_id = nullif(current_setting('app.current_tenant', true), '')::uuid
        )
        """
    )
    op.execute(
        f"""
        CREATE POLICY worker_access ON {table_name}
        USING (current_setting('app.worker_mode', true) = 'on')
        WITH CHECK (current_setting('app.worker_mode', true) = 'on')
        """
    )


def _disable_rls(table_name: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS worker_access ON {table_name}")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")
