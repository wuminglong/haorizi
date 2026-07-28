"""Strict calendar policies and operational plan state.

Revision ID: 20260728_01
Revises:
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260728_01"
down_revision = None
branch_labels = None
depends_on = None


def _columns(inspector: sa.Inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "groups" not in tables:
        from app.db import Base
        from app import models  # noqa: F401

        Base.metadata.create_all(bind=bind)
        return

    group_columns = _columns(inspector, "groups")
    with op.batch_alter_table("groups") as batch:
        if "push_channel" in group_columns:
            batch.drop_column("push_channel")
        if "member_can_edit" in group_columns:
            batch.drop_column("member_can_edit")

    reminder_columns = _columns(inspector, "reminders")
    with op.batch_alter_table("reminders") as batch:
        if "leap_month_policy" not in reminder_columns:
            batch.add_column(sa.Column("leap_month_policy", sa.String(20), nullable=False, server_default="skip"))
        if "missing_day_policy" not in reminder_columns:
            batch.add_column(sa.Column("missing_day_policy", sa.String(20), nullable=False, server_default="last_day"))
        if "importance" in reminder_columns:
            batch.drop_column("importance")
        if "last_edited_by" in reminder_columns:
            batch.drop_column("last_edited_by")

    rule_columns = _columns(inspector, "reminder_rules")
    if "max_attempts" in rule_columns:
        with op.batch_alter_table("reminder_rules") as batch:
            batch.drop_column("max_attempts")

    plan_columns = _columns(inspector, "reminder_plans")
    with op.batch_alter_table("reminder_plans") as batch:
        if "processing_started_at" not in plan_columns:
            batch.add_column(sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True))
        if "sequence" in plan_columns:
            batch.drop_column("sequence")

    rows = bind.execute(
        sa.text(
            "SELECT id, reminder_id, target_date, kind, status FROM reminder_plans "
            "ORDER BY reminder_id, target_date, kind, "
            "CASE status WHEN 'sent' THEN 0 WHEN 'pending' THEN 1 WHEN 'processing' THEN 2 ELSE 3 END, id"
        )
    ).mappings()
    seen: set[tuple[object, object, object]] = set()
    duplicate_ids: list[int] = []
    for row in rows:
        key = (row["reminder_id"], row["target_date"], row["kind"])
        if key in seen:
            duplicate_ids.append(int(row["id"]))
        else:
            seen.add(key)
    if duplicate_ids:
        bind.execute(sa.text("DELETE FROM send_logs WHERE plan_id IN :ids").bindparams(sa.bindparam("ids", expanding=True)), {"ids": duplicate_ids})
        bind.execute(sa.text("DELETE FROM reminder_plans WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True)), {"ids": duplicate_ids})

    unique_names = {item["name"] for item in sa.inspect(bind).get_unique_constraints("reminder_plans")}
    if "uq_reminder_plan_target_kind" not in unique_names:
        with op.batch_alter_table("reminder_plans") as batch:
            batch.create_unique_constraint(
                "uq_reminder_plan_target_kind",
                ["reminder_id", "target_date", "kind"],
            )

    required_unique_constraints = {
        "groups": ("uq_groups_code", ["code"]),
        "reminder_rules": ("uq_reminder_rules_reminder_id", ["reminder_id"]),
    }
    for table_name, (constraint_name, columns) in required_unique_constraints.items():
        unique_columns = {
            tuple(item.get("column_names") or [])
            for item in sa.inspect(bind).get_unique_constraints(table_name)
        }
        if tuple(columns) not in unique_columns:
            with op.batch_alter_table(table_name) as batch:
                batch.create_unique_constraint(constraint_name, columns)

    expected_indexes = {
        "groups": {"ix_groups_code": ["code"], "ix_groups_status": ["status"]},
        "reminders": {"ix_reminders_group_id": ["group_id"]},
        "reminder_rules": {"ix_reminder_rules_reminder_id": ["reminder_id"]},
        "reminder_plans": {
            "ix_reminder_plans_group_id": ["group_id"],
            "ix_reminder_plans_reminder_id": ["reminder_id"],
            "ix_reminder_plans_target_date": ["target_date"],
            "ix_reminder_plans_due_at": ["due_at"],
            "ix_reminder_plans_status": ["status"],
            "ix_reminder_plans_processing_started_at": ["processing_started_at"],
        },
        "send_logs": {
            "ix_send_logs_group_id": ["group_id"],
            "ix_send_logs_reminder_id": ["reminder_id"],
            "ix_send_logs_plan_id": ["plan_id"],
            "ix_send_logs_status": ["status"],
        },
    }
    for table_name, table_indexes in expected_indexes.items():
        table_inspector = sa.inspect(bind)
        existing = {item["name"] for item in table_inspector.get_indexes(table_name)}
        unique_columns = {
            tuple(item.get("column_names") or [])
            for item in table_inspector.get_unique_constraints(table_name)
        }
        for index_name, columns in table_indexes.items():
            if index_name not in existing and tuple(columns) not in unique_columns:
                op.create_index(index_name, table_name, columns, unique=False)


def downgrade() -> None:
    with op.batch_alter_table("reminder_plans") as batch:
        batch.drop_constraint("uq_reminder_plan_target_kind", type_="unique")
        batch.drop_index("ix_reminder_plans_processing_started_at")
        batch.add_column(sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"))
        batch.drop_column("processing_started_at")
    with op.batch_alter_table("reminder_rules") as batch:
        batch.add_column(sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
    with op.batch_alter_table("reminders") as batch:
        batch.add_column(sa.Column("last_edited_by", sa.String(50), nullable=True))
        batch.add_column(sa.Column("importance", sa.String(20), nullable=False, server_default="normal"))
        batch.drop_column("missing_day_policy")
        batch.drop_column("leap_month_policy")
    with op.batch_alter_table("groups") as batch:
        batch.add_column(sa.Column("member_can_edit", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("push_channel", sa.String(20), nullable=False, server_default="pushplus"))
