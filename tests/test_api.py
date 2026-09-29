from __future__ import annotations

def headers(username: str) -> dict[str, str]:
    return {"X-Perspectiv-User": username}


def test_health_and_project_listing(client) -> None:
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["database"] == "ok"
    projects = client.get("/api/v1/projects", headers=headers("admin"))
    assert projects.status_code == 200
    assert projects.json()["total"] >= 1


def test_manager_updates_budget_and_member_cannot_update_project(client) -> None:
    project = client.get("/api/v1/projects", headers=headers("benoit")).json()["items"][0]
    budget = client.post(
        f"/api/v1/projects/{project['id']}/budgets",
        headers=headers("benoit"),
        json={"label": "Budget API"},
    ).json()
    updated = client.patch(
        f"/api/v1/budgets/{budget['id']}",
        headers=headers("benoit"),
        json={"label": "Budget API modifié", "status": "Actif"},
    )
    assert updated.status_code == 200
    assert updated.json()["label"] == "Budget API modifié"
    forbidden = client.patch(
        f"/api/v1/projects/{project['id']}",
        headers=headers("paul"),
        json={"name": "Modification interdite"},
    )
    assert forbidden.status_code == 403


def test_member_can_only_write_own_timesheet(client) -> None:
    project = client.get("/api/v1/projects", headers=headers("paul")).json()["items"][0]
    tasks = client.get(f"/api/v1/projects/{project['id']}/tasks", headers=headers("paul")).json()["items"]
    parent_ids = {task["parent_id"] for task in tasks if task["parent_id"]}
    direct_task = next(task for task in tasks if task["id"] not in parent_ids)
    users = client.get("/api/v1/users", headers=headers("benoit")).json()["items"]
    other_user = next(user for user in users if user["username"] == "benoit")
    payload = {
        "project_id": project["id"],
        "user_id": other_user["id"],
        "week_start": "2026-09-28",
        "entries": [{"task_id": direct_task["id"], "hours": [1, 0, 0, 0, 0, 0, 0]}],
    }
    forbidden = client.put("/api/v1/timesheets/week", headers=headers("paul"), json=payload)
    assert forbidden.status_code == 403


def test_weekly_timesheet_is_idempotent(client) -> None:
    project = client.get("/api/v1/projects", headers=headers("paul")).json()["items"][0]
    tasks = client.get(f"/api/v1/projects/{project['id']}/tasks", headers=headers("paul")).json()["items"]
    parent_ids = {task["parent_id"] for task in tasks if task["parent_id"]}
    direct_task = next(task for task in tasks if task["id"] not in parent_ids)
    payload = {
        "project_id": project["id"],
        "week_start": "2026-09-28",
        "entries": [{"task_id": direct_task["id"], "hours": [1, 2, 0, 0, 0, 0, 0]}],
    }
    idempotency = {**headers("paul"), "Idempotency-Key": "test-week-1"}
    first = client.put("/api/v1/timesheets/week", headers=idempotency, json=payload)
    second = client.put("/api/v1/timesheets/week", headers=idempotency, json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    entries = client.get(f"/api/v1/time-entries?project_id={project['id']}", headers=headers("paul")).json()["items"]
    matching = [entry for entry in entries if entry["task_id"] == direct_task["id"] and entry["entry_date"] in {"2026-09-28", "2026-09-29"}]
    assert len(matching) == 2


def test_delete_requires_fresh_confirmation(client) -> None:
    project = client.get("/api/v1/projects", headers=headers("admin")).json()["items"][0]
    budget = client.post(f"/api/v1/projects/{project['id']}/budgets", headers=headers("admin"), json={"label": "À supprimer"}).json()
    preview = client.post(f"/api/v1/delete/budget/{budget['id']}/preview", headers=headers("admin"))
    assert preview.status_code == 200
    token = preview.json()["confirmation_token"]
    deleted = client.post(f"/api/v1/delete/budget/{budget['id']}/confirm", headers=headers("admin"), json={"confirmation_token": token})
    assert deleted.status_code == 200
    repeated = client.post(f"/api/v1/delete/budget/{budget['id']}/confirm", headers=headers("admin"), json={"confirmation_token": token})
    assert repeated.status_code == 409
