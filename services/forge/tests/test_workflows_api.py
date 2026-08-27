import json
import pytest
from app.models import Dataset, Workflow, WorkflowRun

CSV = "size,rooms,price\n" + "\n".join(f"{100 + i},{2 + i % 3},{200000 + 900 * i}" for i in range(40)) + "\n"

def _dataset(db, owner=1, name="Houses"):
    dataset = Dataset(owner_user_id=owner, is_sample=False, name=name, original_filename="houses.csv", content=CSV, columns=json.dumps(["size", "rooms", "price"]), row_count=40)
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset

def _steps(target="price", algorithm="linear_regression"):
    return [
        {"kind": "load_csv", "params": {}},
        {"kind": "select_target", "params": {"column": target}},
        {"kind": "train_test_split", "params": {"test_size": 0.25, "random_state": 7}},
        {"kind": "train_model", "params": {"algorithm": algorithm}},
        {"kind": "evaluate", "params": {}},
    ]

@pytest.fixture
def no_broker(monkeypatch):
    """Runs are dispatched, never executed, unless a test asks for it."""
    calls = []
    monkeypatch.setattr("app.services.runs.dispatch", lambda task, *args: calls.append(args))
    return calls

def test_create_workflow_stores_one_row_per_step(client, act_as, db):
    act_as(1)
    dataset = _dataset(db)
    response = client.post("/workflows", json={"name": "House prices", "kind": "tabular_regression", "dataset_id": dataset.id, "steps": _steps()})
    assert response.status_code == 201, response.text
    body = response.json()
    assert [s["kind"] for s in body["steps"]] == ["load_csv", "select_target", "train_test_split", "train_model", "evaluate"]
    assert [s["position"] for s in body["steps"]] == [0, 1, 2, 3, 4]
    assert body["steps"][2]["params"] == {"test_size": 0.25, "random_state": 7, "shuffle": True}

def test_unknown_workflow_kind_is_refused(client, act_as, db):
    act_as(1)
    response = client.post("/workflows", json={"name": "x", "kind": "audio_classification", "dataset_id": _dataset(db).id, "steps": _steps()})
    assert response.status_code == 400
    assert "not a workflow kind" in response.json()["detail"]

def test_tabular_workflow_needs_a_dataset(client, act_as):
    act_as(1)
    response = client.post("/workflows", json={"name": "x", "kind": "tabular_regression", "dataset_id": None, "steps": _steps()})
    assert response.status_code == 400
    assert "needs a dataset" in response.json()["detail"]

def test_step_the_kind_does_not_have_is_refused(client, act_as, db):
    act_as(1)
    steps = _steps()
    steps.insert(1, {"kind": "lag_features", "params": {"column": "price", "lags": 3, "horizon": 1}})
    response = client.post("/workflows", json={"name": "x", "kind": "tabular_regression", "dataset_id": _dataset(db).id, "steps": steps})
    assert response.status_code == 400
    assert "has no 'lag_features' step" in response.json()["detail"]

def test_workflow_without_evaluate_is_refused(client, act_as, db):
    act_as(1)
    steps = [s for s in _steps() if s["kind"] != "evaluate"]
    response = client.post("/workflows", json={"name": "x", "kind": "tabular_regression", "dataset_id": _dataset(db).id, "steps": steps})
    assert response.status_code == 400
    assert "evaluate" in response.json()["detail"]

def test_hyperparameter_not_on_the_allow_list_is_refused(client, act_as, db):
    act_as(1)
    steps = _steps()
    steps[3]["params"]["hyperparameters"] = {"n_jobs": -1}
    response = client.post("/workflows", json={"name": "x", "kind": "tabular_regression", "dataset_id": _dataset(db).id, "steps": steps})
    assert response.status_code == 400
    assert "n_jobs" in response.json()["detail"]

def test_llm_workflow_needs_no_dataset(client, act_as):
    act_as(1)
    response = client.post("/workflows", json={"name": "Playground", "kind": "llm_playground", "steps": [{"kind": "prompt", "params": {"prompt": "hello"}}]})
    assert response.status_code == 201
    assert response.json()["dataset_id"] is None
    assert response.json()["steps"][0]["params"]["max_tokens"] == 500

def test_llm_workflow_needs_a_prompt(client, act_as):
    act_as(1)
    response = client.post("/workflows", json={"name": "Playground", "kind": "llm_playground", "steps": [{"kind": "prompt", "params": {"prompt": "  "}}]})
    assert response.status_code == 400

def test_list_shows_only_your_own(client, act_as, db):
    act_as(1)
    client.post("/workflows", json={"name": "Mine", "kind": "tabular_regression", "dataset_id": _dataset(db).id, "steps": _steps()})
    act_as(2)
    assert client.get("/workflows").json()["total"] == 0

def test_someone_elses_workflow_is_404_not_403(client, act_as, db):
    act_as(1)
    created = client.post("/workflows", json={"name": "Mine", "kind": "tabular_regression", "dataset_id": _dataset(db).id, "steps": _steps()}).json()
    act_as(2)
    for call in (client.get(f"/workflows/{created['id']}"), client.delete(f"/workflows/{created['id']}"), client.get(f"/workflows/{created['id']}/code"), client.get(f"/workflows/{created['id']}/runs")):
        assert call.status_code == 404
        assert call.json()["detail"] == "Workflow not found"

def test_replace_steps_swaps_every_row(client, act_as, db):
    act_as(1)
    created = client.post("/workflows", json={"name": "Mine", "kind": "tabular_regression", "dataset_id": _dataset(db).id, "steps": _steps()}).json()
    replacement = _steps(algorithm="ridge")
    replacement.insert(1, {"kind": "scale_features", "params": {"strategy": "minmax"}})
    response = client.put(f"/workflows/{created['id']}/steps", json={"steps": replacement})
    assert response.status_code == 200
    assert [s["kind"] for s in response.json()["steps"]] == ["load_csv", "scale_features", "select_target", "train_test_split", "train_model", "evaluate"]
    assert db.query(__import__("app.models", fromlist=["WorkflowStep"]).WorkflowStep).count() == 6

def test_delete_takes_the_steps_and_runs_with_it(client, act_as, db, no_broker):
    act_as(1)
    created = client.post("/workflows", json={"name": "Mine", "kind": "tabular_regression", "dataset_id": _dataset(db).id, "steps": _steps()}).json()
    client.post(f"/workflows/{created['id']}/runs")
    assert client.delete(f"/workflows/{created['id']}").status_code == 204
    assert db.query(Workflow).count() == 0
    assert db.query(WorkflowRun).count() == 0

def test_step_catalog_lists_the_vocabulary(client, act_as):
    act_as(1)
    body = client.get("/workflows/steps").json()
    assert {s["kind"] for s in body["steps"]} >= {"load_csv", "handle_missing", "encode_categorical", "scale_features", "select_features", "select_target", "lag_features", "train_test_split", "train_model", "evaluate", "prompt"}
    assert body["steps_by_workflow_kind"]["llm_playground"] == ["prompt"]

def test_run_is_queued_and_kept(client, act_as, db, no_broker):
    act_as(1)
    created = client.post("/workflows", json={"name": "Mine", "kind": "tabular_regression", "dataset_id": _dataset(db).id, "steps": _steps()}).json()
    response = client.post(f"/workflows/{created['id']}/runs")
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert no_broker == [(response.json()["id"],)]
    history = client.get(f"/workflows/{created['id']}/runs").json()
    assert history["total"] == 1
    assert client.get(f"/workflows/{created['id']}/runs/{response.json()['id']}").json()["status"] == "queued"

def test_a_broker_that_is_down_answers_503_and_marks_the_run(client, act_as, db, monkeypatch):
    from app.celery_app import BrokerUnavailableError

    act_as(1)
    created = client.post("/workflows", json={"name": "Mine", "kind": "tabular_regression", "dataset_id": _dataset(db).id, "steps": _steps()}).json()

    def _down(task, *args):
        raise BrokerUnavailableError("Training is temporarily unavailable. Try again shortly.")

    monkeypatch.setattr("app.services.runs.dispatch", _down)
    response = client.post(f"/workflows/{created['id']}/runs")
    assert response.status_code == 503
    run = db.query(WorkflowRun).one()
    assert run.status == "failed"
    assert "temporarily unavailable" in run.error

def test_run_of_someone_elses_workflow_is_404(client, act_as, db, no_broker):
    act_as(1)
    created = client.post("/workflows", json={"name": "Mine", "kind": "tabular_regression", "dataset_id": _dataset(db).id, "steps": _steps()}).json()
    run_id = client.post(f"/workflows/{created['id']}/runs").json()["id"]
    act_as(2)
    assert client.get(f"/workflows/{created['id']}/runs/{run_id}").status_code == 404

def test_run_needs_the_dataset_to_still_exist(client, act_as, db, no_broker):
    act_as(1)
    dataset = _dataset(db)
    created = client.post("/workflows", json={"name": "Mine", "kind": "tabular_regression", "dataset_id": dataset.id, "steps": _steps()}).json()
    client.delete(f"/datasets/{dataset.id}")
    response = client.post(f"/workflows/{created['id']}/runs")
    assert response.status_code == 400
    assert "has been deleted" in response.json()["detail"]
