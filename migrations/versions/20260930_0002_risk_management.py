"""Ajoute la gestion des analyses de risques produit."""

from alembic import op
import sqlalchemy as sa


revision = "20260930_0002"
down_revision = "20260929_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "risk_assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("reference", sa.String(48), nullable=False),
        sa.Column("title", sa.String(220), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("product_or_change", sa.Text()),
        sa.Column("scope", sa.Text()),
        sa.Column("assumptions", sa.Text()),
        sa.Column("applicable_requirements", sa.Text()),
        sa.Column("standards", sa.Text(), nullable=False),
        sa.Column("acceptance_threshold", sa.String(16), nullable=False),
        sa.Column("leader_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("is_itns", sa.Boolean(), nullable=False),
        sa.Column("safety_importance", sa.String(32), nullable=False),
        sa.Column("graded_approach_rationale", sa.Text()),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("closed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("reference"),
        sa.UniqueConstraint("project_id", "reference", name="uq_project_risk_assessment_reference"),
    )
    op.create_index("ix_risk_assessments_project_id", "risk_assessments", ["project_id"])
    op.create_index("ix_risk_assessments_reference", "risk_assessments", ["reference"])
    op.create_index("ix_risk_assessments_leader_id", "risk_assessments", ["leader_id"])

    op.create_table(
        "risks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("risk_assessments.id"), nullable=False),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column("lifecycle_phase", sa.String(80), nullable=False),
        sa.Column("activity", sa.String(220), nullable=False),
        sa.Column("hazard", sa.String(220), nullable=False),
        sa.Column("cause", sa.Text()),
        sa.Column("potential_consequence", sa.Text(), nullable=False),
        sa.Column("existing_controls", sa.Text()),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("initial_likelihood", sa.String(1), nullable=False),
        sa.Column("initial_consequence", sa.Integer(), nullable=False),
        sa.Column("initial_level", sa.String(16), nullable=False),
        sa.Column("acceptance_status", sa.String(32), nullable=False),
        sa.Column("acceptance_justification", sa.Text()),
        sa.Column("acceptance_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("acceptance_date", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("reference"),
        sa.UniqueConstraint("assessment_id", "reference", name="uq_assessment_risk_reference"),
    )
    op.create_index("ix_risks_assessment_id", "risks", ["assessment_id"])
    op.create_index("ix_risks_reference", "risks", ["reference"])
    op.create_index("ix_risks_owner_id", "risks", ["owner_id"])
    op.create_index("ix_risks_acceptance_user_id", "risks", ["acceptance_user_id"])

    op.create_table(
        "risk_iterations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("risk_id", sa.Integer(), sa.ForeignKey("risks.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("treatment", sa.Text(), nullable=False),
        sa.Column("reduction_objective", sa.Text()),
        sa.Column("additional_controls", sa.Text()),
        sa.Column("contingency_plan", sa.Text()),
        sa.Column("target_likelihood", sa.String(1), nullable=False),
        sa.Column("target_consequence", sa.Integer(), nullable=False),
        sa.Column("target_level", sa.String(16), nullable=False),
        sa.Column("verification_status", sa.String(32), nullable=False),
        sa.Column("verified_likelihood", sa.String(1)),
        sa.Column("verified_consequence", sa.Integer()),
        sa.Column("verified_level", sa.String(16)),
        sa.Column("verification_evidence", sa.Text()),
        sa.Column("verifier_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("verified_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("risk_id", "sequence", name="uq_risk_iteration_sequence"),
    )
    op.create_index("ix_risk_iterations_risk_id", "risk_iterations", ["risk_id"])
    op.create_index("ix_risk_iterations_verifier_id", "risk_iterations", ["verifier_id"])

    op.create_table(
        "risk_iteration_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("iteration_id", sa.Integer(), sa.ForeignKey("risk_iterations.id"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.UniqueConstraint("iteration_id", "task_id", name="uq_risk_iteration_task"),
    )
    op.create_index("ix_risk_iteration_tasks_iteration_id", "risk_iteration_tasks", ["iteration_id"])
    op.create_index("ix_risk_iteration_tasks_task_id", "risk_iteration_tasks", ["task_id"])


def downgrade() -> None:
    op.drop_table("risk_iteration_tasks")
    op.drop_table("risk_iterations")
    op.drop_table("risks")
    op.drop_table("risk_assessments")
