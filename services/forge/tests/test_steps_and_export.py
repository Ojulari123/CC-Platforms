import json
import types
import pytest
from app.models import Dataset, Workflow, WorkflowStep
from app.services.steps import StepError, validate_sequence, validate_step

def _err(kind, params, workflow_kind="tabular_regression"):
    with pytest.raises(StepError) as excinfo:
        validate_step(workflow_kind, kind, params)
    return str(excinfo.value)

def test_defaults_are_filled_in_so_the_ui_never_has_to_guess():
    assert validate_step("tabular_regression", "handle_missing", {}) == {"strategy": "drop_rows", "columns": []}
    assert validate_step("tabular_regression", "encode_categorical", {}) == {"strategy": "one_hot", "columns": []}
    assert validate_step("tabular_regression", "scale_features", {}) == {"strategy": "standard", "columns": []}
    assert validate_step("tabular_regression", "train_test_split", {}) == {"test_size": 0.2, "random_state": 42, "shuffle": True}

@pytest.mark.parametrize("kind,params,fragment", [
    ("handle_missing", {"strategy": "guess"}, "must be one of"),
    ("handle_missing", {"strategy": "constant"}, "needs a 'fill_value'"),
    ("handle_missing", {"columns": "price"}, "list of column names"),
    ("encode_categorical", {"strategy": "hash"}, "must be one of"),
    ("scale_features", {"strategy": "robust"}, "must be one of"),
    ("select_target", {"column": "  "}, "Choose the column"),
    ("select_features", {"columns": [1, 2]}, "list of column names"),
    ("train_test_split", {"test_size": 0.9}, "fraction between"),
    ("train_test_split", {"random_state": "seed"}, "whole number"),
    ("train_model", {"algorithm": "xgboost"}, "must be one of"),
    ("train_model", {"algorithm": "ridge", "hyperparameters": ["n_estimators"]}, "must be an object"),
    ("train_model", {"algorithm": "ridge", "hyperparameters": {"alpha": "high"}}, "must be a number"),
])
def test_every_bad_parameter_says_what_to_do(kind, params, fragment):
    assert fragment in _err(kind, params)

@pytest.mark.parametrize("params,fragment", [
    ({"column": " ", "lags": 3, "horizon": 1}, "value column"),
    ({"column": "sales", "lags": 0, "horizon": 1}, "'lags' must be"),
    ({"column": "sales", "lags": 3, "horizon": 99}, "'horizon' must be"),
])
def test_lag_parameters_are_bounded(params, fragment):
    assert fragment in _err("lag_features", params, workflow_kind="timeseries_forecast")

@pytest.mark.parametrize("params,fragment", [
    ({"prompt": ""}, "Write the prompt"),
    ({"prompt": "hi", "max_tokens": 99_999}, "between 1 and 4000"),
    ({"prompt": "hi", "context": 5}, "must be text"),
    ({"prompt": "hi", "system": 5}, "must be text"),
])
def test_prompt_parameters_are_checked(params, fragment):
    assert fragment in _err("prompt", params, workflow_kind="llm_playground")

def test_params_have_to_be_an_object():
    assert "must be an object" in _err("evaluate", ["load"])

def test_an_unknown_workflow_kind_is_named():
    assert "Unknown workflow kind" in _err("evaluate", {}, workflow_kind="audio")

@pytest.mark.parametrize("steps,fragment", [
    ([], "at least one step"),
    ([("select_target", {"column": "p"}), ("train_model", {"algorithm": "ridge"}), ("evaluate", {})], "first step must be 'load_csv'"),
    ([("load_csv", {}), ("load_csv", {}), ("select_target", {"column": "p"}), ("train_model", {"algorithm": "ridge"}), ("evaluate", {})], "Only the first step"),
    ([("load_csv", {}), ("select_target", {"column": "p"}), ("evaluate", {}), ("train_model", {"algorithm": "ridge"})], "has to come after"),
    ([("load_csv", {}), ("train_model", {"algorithm": "ridge"}), ("evaluate", {})], "select_target"),
])
def test_the_sequence_is_checked_as_a_whole(steps, fragment):
    with pytest.raises(StepError) as excinfo:
        validate_sequence("tabular_regression", steps)
    assert fragment in str(excinfo.value)

def test_a_forecast_without_lags_is_refused():
    with pytest.raises(StepError) as excinfo:
        validate_sequence("timeseries_forecast", [("load_csv", {}), ("train_model", {"algorithm": "ridge"}), ("evaluate", {})])
    assert "lag_features" in str(excinfo.value)

def test_a_playground_is_exactly_one_prompt():
    with pytest.raises(StepError) as excinfo:
        validate_sequence("llm_playground", [("prompt", {"prompt": "a"}), ("prompt", {"prompt": "b"})])
    assert "exactly one 'prompt' step" in str(excinfo.value)

CSV = "size,price\n" + "\n".join(f"{50 + i},{100000 + 900 * i}" for i in range(40)) + "\n"

def _workflow(client, db, act_as):
    act_as(1)
    dataset = Dataset(owner_user_id=1, is_sample=False, name="Houses", original_filename="houses.csv", content=CSV, columns=json.dumps(["size", "price"]), row_count=40)
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return client.post("/workflows", json={"name": "House prices", "kind": "tabular_regression", "dataset_id": dataset.id, "steps": [
        {"kind": "load_csv", "params": {}},
        {"kind": "select_target", "params": {"column": "price"}},
        {"kind": "train_test_split", "params": {"test_size": 0.2}},
        {"kind": "train_model", "params": {"algorithm": "ridge"}},
        {"kind": "evaluate", "params": {}},
    ]}).json()

def test_the_export_names_the_uploaded_file_and_the_steps(client, act_as, db):
    created = _workflow(client, db, act_as)
    body = client.get(f"/workflows/{created['id']}/code").json()
    assert body["filename"] == "house_prices.py"
    assert body["language"] == "python"
    assert "DATA_PATH = 'houses.csv'" in body["code"]
    assert "— select_target:" in body["code"]
    compile(body["code"], "generated.py", "exec")

def test_the_notebook_export_is_valid_json(client, act_as, db):
    created = _workflow(client, db, act_as)
    body = client.get(f"/workflows/{created['id']}/code", params={"fmt": "notebook"}).json()
    assert body["filename"] == "house_prices.ipynb"
    assert json.loads(body["code"])["nbformat"] == 4

def test_the_raw_export_downloads_as_a_file(client, act_as, db):
    created = _workflow(client, db, act_as)
    response = client.get(f"/workflows/{created['id']}/code/raw")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="house_prices.py"'
    assert response.text.startswith('"""')

def test_the_celery_task_runs_the_real_thing(db, monkeypatch, test_sessionmaker):
    from app import tasks
    from app.services.ai_provider import AIResult

    monkeypatch.setattr("app.tasks.SessionLocal", test_sessionmaker)
    monkeypatch.setattr("app.services.runs.generate", lambda system, user, *, max_tokens: AIResult(text="hi", model="m", token_count=3))
    workflow = Workflow(owner_user_id=1, name="Ask", kind="llm_playground", dataset_id=None)
    workflow.steps = [WorkflowStep(position=0, kind="prompt", params=json.dumps({"prompt": "hi", "max_tokens": 10}))]
    db.add(workflow)
    db.commit()
    from app.models import WorkflowRun

    run = WorkflowRun(workflow_id=workflow.id, owner_user_id=1, status="queued")
    db.add(run)
    db.commit()
    db.refresh(run)
    assert tasks.execute_run(run.id) == "succeeded"

def test_the_provider_wrapper_returns_text_and_never_leaks_the_key(monkeypatch):
    import openai
    from app.services import ai_provider

    monkeypatch.setattr("app.config.settings.LLM_API_KEY", "test-key-not-real")
    captured = {}

    class _Completions:

        def create(self, **kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=" hello "))],
                model="gpt-4o-mini-2024-07-18",
                usage=types.SimpleNamespace(total_tokens=17),
            )

    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: types.SimpleNamespace(chat=types.SimpleNamespace(completions=_Completions())))
    result = ai_provider.generate("be brief", "hello", max_tokens=25)
    assert (result.text, result.model, result.token_count) == ("hello", "gpt-4o-mini-2024-07-18", 17)
    assert captured["max_tokens"] == 25

def test_a_provider_exception_becomes_one_sentence(monkeypatch):
    import openai
    from app.services import ai_provider
    from app.services.ai_provider import AIError

    monkeypatch.setattr("app.config.settings.LLM_API_KEY", "test-key-not-real")

    class _Boom:

        def create(self, **kwargs):
            raise RuntimeError("429 rate limited for org-abc123 request req_xyz")

    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: types.SimpleNamespace(chat=types.SimpleNamespace(completions=_Boom())))
    with pytest.raises(AIError) as excinfo:
        ai_provider.generate("s", "u", max_tokens=5)
    assert str(excinfo.value) == "The language model could not be reached. Try again shortly."
    assert "org-abc123" not in str(excinfo.value)

def test_an_empty_reply_is_reported_rather_than_stored(monkeypatch):
    import openai
    from app.services import ai_provider
    from app.services.ai_provider import AIError

    monkeypatch.setattr("app.config.settings.LLM_API_KEY", "test-key-not-real")

    class _Blank:

        def create(self, **kwargs):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=""))], model="m", usage=None)

    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: types.SimpleNamespace(chat=types.SimpleNamespace(completions=_Blank())))
    with pytest.raises(AIError) as excinfo:
        ai_provider.generate("s", "u", max_tokens=5)
    assert "empty reply" in str(excinfo.value)
