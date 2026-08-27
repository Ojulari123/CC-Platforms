import json
from datetime import datetime, timedelta, timezone
import pytest
from app.models import LlmUsage, Workflow, WorkflowRun, WorkflowStep
from app.services import llm_budget, runs as run_service
from app.services.ai_provider import AIError, AIResult

PROMPT = {"system": "Answer only from the text.", "prompt": "Who fixed it?", "context": "Ada fixed the timeout.", "max_tokens": 120}

def _playground(db, owner=1, params=None):
    workflow = Workflow(owner_user_id=owner, name="Ask my notes", kind="llm_playground", dataset_id=None)
    workflow.steps = [WorkflowStep(position=0, kind="prompt", params=json.dumps(params or PROMPT))]
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow

def _run_row(db, workflow, owner=1):
    run = WorkflowRun(workflow_id=workflow.id, owner_user_id=owner, status="queued")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run

def _reply(text="Ada did.", tokens=42):
    return lambda system, user, *, max_tokens: AIResult(text=text, model="gpt-4o-mini", token_count=tokens)

def test_a_playground_run_stores_the_reply_and_meters_the_spend(db, monkeypatch):
    monkeypatch.setattr("app.services.runs.generate", _reply())
    workflow = _playground(db)
    run = run_service.execute_run(db, _run_row(db, workflow).id)
    assert run.status == "succeeded"
    assert json.loads(run.result)["reply"] == "Ada did."
    assert json.loads(run.result)["grounded"] is True
    assert json.loads(run.metrics)["tokens"] == 42
    usage = db.query(LlmUsage).one()
    assert (usage.user_id, usage.run_id, usage.tokens, usage.kind) == (1, run.id, 42, "playground")

def test_the_context_is_what_the_model_is_told_to_answer_from(db, monkeypatch):
    seen = {}

    def _capture(system, user, *, max_tokens):
        seen["system"], seen["user"], seen["max_tokens"] = system, user, max_tokens
        return AIResult(text="ok", model="gpt-4o-mini", token_count=10)

    monkeypatch.setattr("app.services.runs.generate", _capture)
    run_service.execute_run(db, _run_row(db, _playground(db)).id)
    assert seen["system"] == "Answer only from the text."
    assert "Ada fixed the timeout." in seen["user"] and "Who fixed it?" in seen["user"]
    assert seen["max_tokens"] == 120

def test_a_provider_failure_reaches_the_learner_as_a_sentence(db, monkeypatch):
    def _boom(system, user, *, max_tokens):
        raise AIError("The language model could not be reached. Try again shortly.")

    monkeypatch.setattr("app.services.runs.generate", _boom)
    run = run_service.execute_run(db, _run_row(db, _playground(db)).id)
    assert run.status == "failed"
    assert run.error == "The language model could not be reached. Try again shortly."
    assert db.query(LlmUsage).count() == 0

def test_an_unforeseen_failure_is_not_a_traceback(db, monkeypatch):
    def _boom(system, user, *, max_tokens):
        raise KeyError("choices")

    monkeypatch.setattr("app.services.runs.generate", _boom)
    run = run_service.execute_run(db, _run_row(db, _playground(db)).id)
    assert run.status == "failed"
    assert "Something went wrong" in run.error and "Traceback" not in run.error
    assert "KeyError" in run.error  # the class name is a hint, the stack is not

def test_a_spent_allowance_refuses_the_run_before_the_call(client, act_as, db, monkeypatch):
    monkeypatch.setattr("app.config.settings.LLM_DAILY_TOKEN_CAP", 100)
    act_as(1)
    workflow = _playground(db)
    db.add(LlmUsage(user_id=1, run_id=None, tokens=100))
    db.commit()
    response = client.post(f"/workflows/{workflow.id}/runs")
    assert response.status_code == 429
    assert "daily tokens left" in response.json()["detail"]
    assert db.query(WorkflowRun).count() == 0

def test_yesterdays_spend_does_not_count_against_today(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.LLM_DAILY_TOKEN_CAP", 100)
    db.add(LlmUsage(user_id=1, run_id=None, tokens=500, created_at=datetime.now(timezone.utc) - timedelta(days=2)))
    db.commit()
    assert llm_budget.tokens_used_today(db, 1) == 0
    llm_budget.check_budget(db, 1, about_to_spend=50)

def test_a_cap_of_zero_is_off(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.LLM_DAILY_TOKEN_CAP", 0)
    db.add(LlmUsage(user_id=1, run_id=None, tokens=10_000_000))
    db.commit()
    llm_budget.check_budget(db, 1, about_to_spend=999_999)

def test_the_estimate_sits_above_a_plain_character_count():
    assert llm_budget.estimate_tokens("") == 4
    assert llm_budget.estimate_tokens("amqp==5.3.1") >= 7
    assert llm_budget.estimate_tokens("héllo wörld") > llm_budget.estimate_tokens("hello world")

def test_a_missing_key_disables_the_playground_and_names_no_variable(monkeypatch):
    from app.services import ai_provider

    monkeypatch.setattr("app.config.settings.LLM_API_KEY", "")
    assert ai_provider.is_configured() is False
    with pytest.raises(AIError) as excinfo:
        ai_provider.generate("s", "u", max_tokens=10)
    assert "not set up on this server" in str(excinfo.value)
    assert "LLM_API_KEY" not in str(excinfo.value)

def test_deleting_a_workflow_takes_its_queued_runs_with_it(db):
    workflow = _playground(db)
    run_id = _run_row(db, workflow).id
    db.delete(workflow)
    db.commit()
    assert db.get(WorkflowRun, run_id) is None

def test_a_run_that_no_longer_exists_is_not_retried_forever(db):
    with pytest.raises(ValueError):
        run_service.execute_run(db, 9999)

def test_a_tabular_run_records_timing_and_the_dataset_it_used(db, monkeypatch):
    from app.models import Dataset

    csv = "size,price\n" + "\n".join(f"{50 + i},{100000 + 900 * i}" for i in range(40)) + "\n"
    dataset = Dataset(owner_user_id=1, is_sample=False, name="Houses", original_filename="houses.csv", content=csv, columns=json.dumps(["size", "price"]), row_count=40)
    db.add(dataset)
    db.commit()
    workflow = Workflow(owner_user_id=1, name="Prices", kind="tabular_regression", dataset_id=dataset.id)
    workflow.steps = [
        WorkflowStep(position=0, kind="load_csv", params="{}"),
        WorkflowStep(position=1, kind="select_target", params=json.dumps({"column": "price"})),
        WorkflowStep(position=2, kind="train_test_split", params=json.dumps({"test_size": 0.25, "random_state": 1, "shuffle": True})),
        WorkflowStep(position=3, kind="train_model", params=json.dumps({"algorithm": "linear_regression", "hyperparameters": {}})),
        WorkflowStep(position=4, kind="evaluate", params="{}"),
    ]
    db.add(workflow)
    db.commit()
    run = run_service.execute_run(db, _run_row(db, workflow).id)
    assert run.status == "succeeded"
    assert run.duration_ms is not None and run.duration_ms >= 0
    assert run.started_at is not None and run.finished_at is not None
    assert json.loads(run.result)["dataset"] == "Houses"
    assert json.loads(run.metrics)["r2"] > 0.99
