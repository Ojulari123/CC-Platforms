import json
import subprocess
import sys
import pytest
from app.models import Workflow, WorkflowStep
from app.services import codegen

def workflow(kind, name, *pairs):
    return Workflow(id=1, owner_user_id=1, name=name, kind=kind, dataset_id=1), [
        WorkflowStep(position=i, kind=step_kind, params=json.dumps(params)) for i, (step_kind, params) in enumerate(pairs)
    ]

CLASSIFICATION = (
    ("load_csv", {}),
    ("select_target", {"column": "grade"}),
    ("handle_missing", {"strategy": "mean", "columns": []}),
    ("encode_categorical", {"strategy": "one_hot", "columns": []}),
    ("scale_features", {"strategy": "standard", "columns": []}),
    ("train_test_split", {"test_size": 0.25, "random_state": 5, "shuffle": True}),
    ("train_model", {"algorithm": "logistic_regression", "hyperparameters": {"max_iter": 500}}),
    ("evaluate", {}),
)
FORECAST = (
    ("load_csv", {}),
    ("lag_features", {"column": "sales", "lags": 3, "horizon": 2}),
    ("train_test_split", {"test_size": 0.2, "random_state": 5, "shuffle": False}),
    ("train_model", {"algorithm": "random_forest_regressor", "hyperparameters": {"n_estimators": 30}}),
    ("evaluate", {}),
)

def _csv(tmp_path):
    rows = ["hours,city,grade"]
    for i in range(60):
        passing = i % 2 == 0
        rows.append(f"{20 + i if passing else 2 + i % 5},{'lagos' if i % 3 else 'abuja'},{'pass' if passing else 'fail'}")
    path = tmp_path / "students.csv"
    path.write_text("\n".join(rows) + "\n")
    return path

def _series_csv(tmp_path):
    path = tmp_path / "sales.csv"
    path.write_text("month,sales\n" + "\n".join(f"2020-{i % 12 + 1:02d},{1000 + 10 * i + (i % 4) * 25}" for i in range(60)) + "\n")
    return path

def _run(script: str, tmp_path, name: str):
    path = tmp_path / name
    path.write_text(script)
    return subprocess.run([sys.executable, str(path)], capture_output=True, text=True, cwd=tmp_path)

def test_every_step_is_named_in_the_generated_script():
    wf, steps = workflow("tabular_classification", "Student grades", *CLASSIFICATION)
    script = codegen.generate_script(wf, steps, data_path="students.csv")
    for kind in ("load_csv", "select_target", "handle_missing", "encode_categorical", "scale_features", "train_test_split", "train_model", "evaluate"):
        assert f"— {kind}:" in script, kind
    assert "step 1 of 8" in script and "step 8 of 8" in script

def test_generated_classification_script_runs_and_scores(tmp_path):
    wf, steps = workflow("tabular_classification", "Student grades", *CLASSIFICATION)
    script = codegen.generate_script(wf, steps, data_path=str(_csv(tmp_path)))
    proc = _run(script, tmp_path, "student_grades.py")
    assert proc.returncode == 0, proc.stderr
    assert "accuracy:" in proc.stdout
    assert "confusion matrix" in proc.stdout
    assert "60 rows and 3 columns" in proc.stdout

def test_generated_forecast_script_runs_and_scores(tmp_path):
    wf, steps = workflow("timeseries_forecast", "Sales forecast", *FORECAST)
    script = codegen.generate_script(wf, steps, data_path=str(_series_csv(tmp_path)))
    proc = _run(script, tmp_path, "sales_forecast.py")
    assert proc.returncode == 0, proc.stderr
    assert "rmse:" in proc.stdout and "mape:" in proc.stdout

def test_generated_script_and_the_real_run_agree(tmp_path):
    """The Week 7 bar: the export is the run, written out, not a plausible-looking copy."""
    from app.services.execution import run_tabular

    wf, steps = workflow("tabular_classification", "Student grades", *CLASSIFICATION)
    path = _csv(tmp_path)
    metrics, _ = run_tabular("tabular_classification", path.read_text(), steps)
    proc = _run(codegen.generate_script(wf, steps, data_path=str(path)), tmp_path, "student_grades.py")
    assert proc.returncode == 0, proc.stderr
    assert f"accuracy:        {metrics['accuracy']:.4f}" in proc.stdout
    assert f"f1_macro:        {metrics['f1_macro']:.4f}" in proc.stdout

@pytest.mark.parametrize("algorithm", ["logistic_regression", "random_forest_classifier", "decision_tree_classifier"])
def test_every_classifier_generates_something_that_compiles(algorithm):
    steps_with = tuple(("train_model", {"algorithm": algorithm, "hyperparameters": {}}) if k == "train_model" else (k, p) for k, p in CLASSIFICATION)
    wf, steps = workflow("tabular_classification", "x", *steps_with)
    compile(codegen.generate_script(wf, steps), "generated.py", "exec")

@pytest.mark.parametrize("strategy", ["drop_rows", "mean", "median", "most_frequent", "constant"])
def test_every_missing_strategy_generates_something_that_compiles(strategy):
    params = {"strategy": strategy, "columns": ["hours"]} | ({"fill_value": 0} if strategy == "constant" else {})
    steps_with = tuple(("handle_missing", params) if k == "handle_missing" else (k, p) for k, p in CLASSIFICATION)
    wf, steps = workflow("tabular_classification", "x", *steps_with)
    compile(codegen.generate_script(wf, steps), "generated.py", "exec")

def test_ordinal_encoding_and_minmax_scaling_generate_the_right_calls():
    steps_with = tuple(
        ("encode_categorical", {"strategy": "ordinal", "columns": ["city"]}) if k == "encode_categorical"
        else ("scale_features", {"strategy": "minmax", "columns": []}) if k == "scale_features"
        else (k, p)
        for k, p in CLASSIFICATION
    )
    wf, steps = workflow("tabular_classification", "x", *steps_with)
    script = codegen.generate_script(wf, steps)
    assert 'astype("category").cat.codes' in script
    assert "MinMaxScaler()" in script

def test_selected_features_reach_the_script():
    steps_with = CLASSIFICATION[:2] + (("select_features", {"columns": ["hours"]}),) + CLASSIFICATION[2:]
    wf, steps = workflow("tabular_classification", "x", *steps_with)
    script = codegen.generate_script(wf, steps)
    assert "FEATURES = [c for c in ['hours'] if c != TARGET]" in script
    assert "— select_features:" in script

def test_llm_script_never_contains_the_key(tmp_path):
    wf, steps = workflow("llm_playground", "Ask my notes", ("prompt", {"system": "Be brief.", "prompt": "What broke?", "context": "The sync timed out.", "max_tokens": 100}))
    script = codegen.generate_script(wf, steps, model="gpt-4o-mini")
    compile(script, "generated.py", "exec")
    assert 'os.environ["OPENAI_API_KEY"]' in script
    assert "sk-" not in script
    assert "'What broke?'" in script

def test_notebook_export_is_one_cell_per_step():
    wf, steps = workflow("tabular_classification", "Student grades", *CLASSIFICATION)
    notebook = codegen.generate_notebook(wf, steps, data_path="students.csv")
    assert notebook["nbformat"] == 4
    code_cells = [c for c in notebook["cells"] if c["cell_type"] == "code"]
    # Nine blocks (the eight steps plus the derived features-and-target block) and the imports cell.
    assert len(code_cells) == 10
    assert json.dumps(notebook)  # serialisable, which is what the endpoint returns
    assert codegen.notebook_filename(wf) == "student_grades.ipynb"

def test_a_workflow_with_no_steps_cannot_be_exported():
    wf, _ = workflow("tabular_classification", "x")
    with pytest.raises(ValueError):
        codegen.generate_script(wf, [])
