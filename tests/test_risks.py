from __future__ import annotations

from sqlalchemy import select

from perspectiv.database import session_scope
from perspectiv.models import Project, User
from perspectiv.services import (
    RISK_MATRIX,
    create_risk,
    create_risk_assessment,
    create_risk_iteration,
    decide_risk_acceptance,
    risk_level,
    set_risk_assessment_status,
    verify_risk_iteration,
)


EXPECTED_MATRIX = {
    "A": ["Medium", "Medium", "High", "Extreme", "Extreme"],
    "B": ["Low", "Medium", "High", "High", "Extreme"],
    "C": ["Low", "Medium", "Medium", "High", "High"],
    "D": ["Low", "Low", "Medium", "Medium", "Medium"],
    "E": ["Low", "Low", "Low", "Low", "Medium"],
}


def test_risk_matrix_matches_reference_workbook() -> None:
    assert sum(len(row) for row in RISK_MATRIX.values()) == 25
    for likelihood, levels in EXPECTED_MATRIX.items():
        for consequence, expected in enumerate(levels, start=1):
            assert risk_level(likelihood, consequence) == expected


def test_verified_residual_and_human_acceptance_workflow(client) -> None:
    with session_scope() as session:
        project = session.scalar(select(Project).where(Project.code == "PRJ-001"))
        user = session.scalar(select(User).where(User.username == "benoit"))
        assessment = create_risk_assessment(session, project.id, "Workflow test", user.id)
        risk = create_risk(
            session,
            assessment.id,
            "Conception",
            "Validation",
            "Défaillance non détectée",
            "Couverture insuffisante",
            "Non-conformité produit",
            "Relecture",
            user.id,
            "B",
            4,
        )
        iteration = create_risk_iteration(
            session, risk.id, "Ajouter un essai", "Réduire", "Essai indépendant", "Blocage livraison", "D", 2
        )
        assert risk.initial_level == "High"
        assert iteration.target_level == "Low"
        verify_risk_iteration(session, iteration.id, "D", 2, "PV d'essai validé", user.id)
        decide_risk_acceptance(session, risk.id, "Accepté", "Cotation Low vérifiée.", user.id)
        set_risk_assessment_status(session, assessment.id, "Clôturée")
        assert assessment.status == "Clôturée"


def test_risk_api_permissions_and_matrix(client) -> None:
    headers = {"X-Perspectiv-User": "benoit"}
    project = client.get("/api/v1/projects", headers=headers).json()["items"][0]
    created = client.post(
        f"/api/v1/projects/{project['id']}/risk-assessments",
        headers=headers,
        json={"title": "Analyse API", "acceptance_threshold": "Low"},
    )
    assert created.status_code == 201
    assessment = created.json()
    risk = client.post(
        f"/api/v1/risk-assessments/{assessment['id']}/risks",
        headers=headers,
        json={
            "activity": "Conception",
            "hazard": "Erreur de définition",
            "potential_consequence": "Produit non conforme",
            "initial_likelihood": "C",
            "initial_consequence": 3,
        },
    )
    assert risk.status_code == 201
    matrix = client.get(f"/api/v1/risk-assessments/{assessment['id']}/matrix", headers=headers)
    assert matrix.status_code == 200
    assert matrix.json()["paths"][0]["points"][0]["level"] == "Medium"
    forbidden = client.post(
        f"/api/v1/projects/{project['id']}/risk-assessments",
        headers={"X-Perspectiv-User": "paul"},
        json={"title": "Interdit"},
    )
    assert forbidden.status_code == 403
