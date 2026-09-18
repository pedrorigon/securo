"""budgets that measure a group instead of a single category

The budgets screen has always spoken one language: pick a category, set an
amount. People who think in groups — how much goes to Moradia, to Pets, to
Compras — had no way to say so, and the home's group view could only borrow
the category budgets and add them up.

So a budget may now point at a group instead. One table, one set of rules:
the month-specific override still beats the most recent recurring default,
"repeat every month" still means what it meant, and a check constraint keeps
every row honest — a budget is for a category or for a group, never both and
never neither.

The category column becomes nullable for the group rows. Existing rows are
untouched: they all have a category, so they all mean exactly what they
meant yesterday, and the group-side unique constraint only ever sees group
rows (Postgres treats NULLs as distinct).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "090"
down_revision = "089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("budgets", "category_id", existing_type=UUID(as_uuid=True), nullable=True)
    op.add_column(
        "budgets",
        sa.Column(
            "group_id",
            UUID(as_uuid=True),
            sa.ForeignKey("category_groups.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_budget_single_scope",
        "budgets",
        "(category_id IS NULL) <> (group_id IS NULL)",
    )
    op.create_unique_constraint(
        "uq_budget_per_group_month_type",
        "budgets",
        ["user_id", "group_id", "month", "is_recurring"],
    )


def downgrade() -> None:
    # Group budgets cannot survive a world without the column; removing them
    # is the honest downgrade (the alternative is rows that violate the
    # category backfill below).
    op.execute("DELETE FROM budgets WHERE group_id IS NOT NULL")
    op.drop_constraint("uq_budget_per_group_month_type", "budgets", type_="unique")
    op.drop_constraint("ck_budget_single_scope", "budgets", type_="check")
    op.drop_column("budgets", "group_id")
    op.alter_column("budgets", "category_id", existing_type=UUID(as_uuid=True), nullable=False)
