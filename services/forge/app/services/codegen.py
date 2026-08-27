"""Turns a workflow's step rows into Python a beginner can read and run.

The generator walks the same rows in the same canonical order as execution.py, one block
per step, each labelled with the step it came from. That labelling is the point of Week 7:
a learner should be able to put the canvas and the script side by side and see which line
came from which box.
"""
import json
from app.models import KIND_LLM_PLAYGROUND, KIND_TABULAR_CLASSIFICATION, KIND_TIMESERIES_FORECAST
from app.services.steps import STEP_ENCODE_CATEGORICAL, STEP_EVALUATE, STEP_HANDLE_MISSING, STEP_LAG_FEATURES, STEP_LOAD_CSV, STEP_PROMPT, STEP_SCALE_FEATURES, STEP_SELECT_FEATURES, STEP_SELECT_TARGET, STEP_TRAIN_MODEL, STEP_TRAIN_TEST_SPLIT, ordered_steps

# Constructor text per algorithm, alongside the import it needs. Kept beside the
# generator rather than shared with execution.py: execution builds an object, this builds
# the source that would build it, and merging the two makes both harder to read.
ESTIMATORS = {
    "logistic_regression": ("from sklearn.linear_model import LogisticRegression", "LogisticRegression", {"max_iter": 1000}),
    "random_forest_classifier": ("from sklearn.ensemble import RandomForestClassifier", "RandomForestClassifier", {"n_estimators": 100, "random_state": 42}),
    "decision_tree_classifier": ("from sklearn.tree import DecisionTreeClassifier", "DecisionTreeClassifier", {"random_state": 42}),
    "linear_regression": ("from sklearn.linear_model import LinearRegression", "LinearRegression", {}),
    "ridge": ("from sklearn.linear_model import Ridge", "Ridge", {}),
    "random_forest_regressor": ("from sklearn.ensemble import RandomForestRegressor", "RandomForestRegressor", {"n_estimators": 100, "random_state": 42}),
}

class Block:

    def __init__(self, heading: str, lines: list[str]):
        self.heading = heading
        self.lines = lines

def _params(step) -> dict:
    return json.loads(step.params or "{}")

def _call_args(defaults: dict, hyperparameters: dict) -> str:
    merged = defaults | hyperparameters
    return ", ".join(f"{name}={value!r}" for name, value in merged.items())

def _target_name(steps, kind: str) -> str:
    for step in steps:
        if step.kind == STEP_SELECT_TARGET:
            return _params(step)["column"]
        if step.kind == STEP_LAG_FEATURES and kind == KIND_TIMESERIES_FORECAST:
            params = _params(step)
            return f"{params['column']}_t_plus_{params['horizon']}"
    return ""

def _llm_blocks(steps, model: str) -> tuple[list[str], list[Block]]:
    params = _params(steps[0])
    imports = ["import os", "from openai import OpenAI"]
    user_text = "PROMPT if not CONTEXT else f\"{PROMPT}\\n\\nUse only this text:\\n{CONTEXT}\""
    blocks = [
        Block("step 1 of 1 — prompt: what you asked the model, and what it may answer from", [
            f"SYSTEM = {params.get('system', '')!r}",
            f"PROMPT = {params.get('prompt', '')!r}",
            f"CONTEXT = {params.get('context', '')!r}",
            "",
            "# The key is read from the environment, never written into the file:",
            "#   export OPENAI_API_KEY=your-key-here",
            "client = OpenAI(api_key=os.environ[\"OPENAI_API_KEY\"])",
            f"user_message = {user_text}",
            "response = client.chat.completions.create(",
            f"    model={model!r},",
            f"    max_tokens={params.get('max_tokens', 500)},",
            "    messages=[{\"role\": \"system\", \"content\": SYSTEM}, {\"role\": \"user\", \"content\": user_message}],",
            ")",
            "print(response.choices[0].message.content)",
            "print(f\"tokens used: {response.usage.total_tokens}\")",
        ]),
    ]
    return imports, blocks

def _tabular_blocks(workflow_kind: str, steps, target: str, data_path: str) -> tuple[list[str], list[Block]]:
    # steps arrive in canonical order, so TARGET is always defined by the select_target or
    # lag_features block before anything below reads it.
    imports = ["import pandas as pd"]
    blocks: list[Block] = []
    total = len(steps)
    by_kind = {step.kind: _params(step) for step in steps}
    positions = {step.kind: index + 1 for index, step in enumerate(steps)}

    def heading(kind: str, text: str) -> str:
        return f"step {positions.get(kind, '?')} of {total} — {kind}: {text}"

    blocks.append(Block(heading(STEP_LOAD_CSV, "read the CSV into a table"), [
        f"DATA_PATH = {data_path!r}",
        "",
        "df = pd.read_csv(DATA_PATH)",
        "print(f\"loaded {len(df)} rows and {len(df.columns)} columns\")",
    ]))

    if STEP_SELECT_TARGET in by_kind:
        blocks.append(Block(heading(STEP_SELECT_TARGET, "the column the model predicts"), [
            f"TARGET = {target!r}",
            "if TARGET not in df.columns:",
            "    raise SystemExit(f\"There is no column called {TARGET} in this CSV. It has: {list(df.columns)}\")",
        ]))

    if STEP_LAG_FEATURES in by_kind:
        params = by_kind[STEP_LAG_FEATURES]
        column, lags, horizon = params["column"], params["lags"], params["horizon"]
        shifted = f"series.shift(-{horizon - 1})" if horizon > 1 else "series"
        blocks.append(Block(heading(STEP_LAG_FEATURES, f"turn the series into rows: {lags} previous readings predict {horizon} step(s) ahead"), [
            f"series = pd.to_numeric(df[{column!r}], errors=\"coerce\")",
            f"TARGET = {target!r}",
            f"df = pd.DataFrame({{f\"{column}_lag_{{i}}\": series.shift(i) for i in range(1, {lags + 1})}})",
            f"df[TARGET] = {shifted}",
            "df = df.dropna().reset_index(drop=True)",
            "print(f\"{len(df)} rows once the lags line up\")",
        ]))

    if STEP_HANDLE_MISSING in by_kind:
        params = by_kind[STEP_HANDLE_MISSING]
        strategy = params.get("strategy", "drop_rows")
        columns = params.get("columns") or []
        subset = repr(columns) if columns else "list(df.columns)"
        if strategy == "drop_rows":
            lines = [f"df = df.dropna(subset={subset})"]
        elif strategy == "constant":
            lines = [f"df = df.fillna({{c: {params.get('fill_value')!r} for c in {subset}}})"]
        elif strategy == "most_frequent":
            lines = [f"for column in {subset}:", "    modes = df[column].mode(dropna=True)", "    if len(modes):", "        df[column] = df[column].fillna(modes.iloc[0])"]
        else:
            lines = [
                f"for column in {subset}:",
                "    if df[column].dtype == object:",
                "        modes = df[column].mode(dropna=True)",
                "        if len(modes):",
                "            df[column] = df[column].fillna(modes.iloc[0])",
                "    else:",
                f"        df[column] = df[column].fillna(df[column].{strategy}())",
            ]
        blocks.append(Block(heading(STEP_HANDLE_MISSING, f"gaps in the data, handled by '{strategy}'"), lines + ["print(f\"{len(df)} rows left\")"]))

    if STEP_ENCODE_CATEGORICAL in by_kind:
        params = by_kind[STEP_ENCODE_CATEGORICAL]
        columns = params.get("columns") or []
        chosen = f"[c for c in {columns!r} if c in df.columns and c != TARGET]" if columns else "[c for c in df.columns if df[c].dtype == object and c != TARGET]"
        if params.get("strategy", "one_hot") == "ordinal":
            lines = [f"categorical = {chosen}", "for column in categorical:", "    df[column] = df[column].astype(\"category\").cat.codes"]
            note = "each category becomes a number"
        else:
            lines = [f"categorical = {chosen}", "df = pd.get_dummies(df, columns=categorical, dummy_na=False)"]
            note = "each category becomes its own 0/1 column"
        blocks.append(Block(heading(STEP_ENCODE_CATEGORICAL, f"text columns the model cannot read, {note}"), lines + ["print(f\"encoded: {categorical}\")"]))

    feature_columns = (by_kind.get(STEP_SELECT_FEATURES) or {}).get("columns") or []
    feature_expr = f"[c for c in {feature_columns!r} if c != TARGET]" if feature_columns else "[c for c in df.columns if c != TARGET]"
    select_heading = heading(STEP_SELECT_FEATURES, "the columns the model learns from") if STEP_SELECT_FEATURES in by_kind else "features and target: everything except the target column"
    coerce = ["y = pd.to_numeric(y, errors=\"coerce\").dropna()", "X = X.loc[y.index]"] if workflow_kind != KIND_TABULAR_CLASSIFICATION else []
    blocks.append(Block(select_heading, [
        f"FEATURES = {feature_expr}",
        "prepared = df[FEATURES + [TARGET]].dropna()",
        "X = prepared[FEATURES]",
        "y = prepared[TARGET]",
        *coerce,
        "print(f\"{len(X)} usable rows, {len(FEATURES)} features, predicting {TARGET}\")",
    ]))

    split = by_kind.get(STEP_TRAIN_TEST_SPLIT) or {"test_size": 0.2, "random_state": 42, "shuffle": workflow_kind != KIND_TIMESERIES_FORECAST}
    imports.append("from sklearn.model_selection import train_test_split")
    stratify = "y if y.value_counts().min() >= 2 else None" if workflow_kind == KIND_TABULAR_CLASSIFICATION and split.get("shuffle", True) else "None"
    blocks.append(Block(heading(STEP_TRAIN_TEST_SPLIT, f"hold back {int(float(split.get('test_size', 0.2)) * 100)}% of the rows to score on"), [
        "X_train, X_test, y_train, y_test = train_test_split(",
        f"    X, y, test_size={split.get('test_size', 0.2)}, random_state={split.get('random_state', 42)}, shuffle={bool(split.get('shuffle', True))}, stratify={stratify},",
        ")",
        "print(f\"{len(X_train)} rows to train on, {len(X_test)} held back\")",
    ]))

    if STEP_SCALE_FEATURES in by_kind:
        params = by_kind[STEP_SCALE_FEATURES]
        name = "MinMaxScaler" if params.get("strategy") == "minmax" else "StandardScaler"
        imports.append(f"from sklearn.preprocessing import {name}")
        blocks.append(Block(heading(STEP_SCALE_FEATURES, "put the numbers on a comparable range"), [
            f"scaler = {name}()",
            "# Fitted on the training rows only. A scaler fitted on everything has already",
            "# seen the test set, and the score it produces flatters the model.",
            "X_train = scaler.fit_transform(X_train)",
            "X_test = scaler.transform(X_test)",
        ]))

    model_params = by_kind.get(STEP_TRAIN_MODEL) or {}
    algorithm = model_params.get("algorithm", "linear_regression")
    import_line, class_name, defaults = ESTIMATORS[algorithm]
    imports.append(import_line)
    blocks.append(Block(heading(STEP_TRAIN_MODEL, f"fit {algorithm} on the training rows"), [
        f"model = {class_name}({_call_args(defaults, model_params.get('hyperparameters') or {})})",
        "model.fit(X_train, y_train)",
        "predictions = model.predict(X_test)",
    ]))

    if workflow_kind == KIND_TABULAR_CLASSIFICATION:
        imports.append("from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score")
        lines = [
            "print(f\"accuracy:        {accuracy_score(y_test, predictions):.4f}\")",
            "print(f\"precision_macro: {precision_score(y_test, predictions, average='macro', zero_division=0):.4f}\")",
            "print(f\"recall_macro:    {recall_score(y_test, predictions, average='macro', zero_division=0):.4f}\")",
            "print(f\"f1_macro:        {f1_score(y_test, predictions, average='macro', zero_division=0):.4f}\")",
            "print(\"confusion matrix (rows are the true class):\")",
            "print(confusion_matrix(y_test, predictions))",
        ]
    else:
        imports.append("from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score")
        lines = [
            "print(f\"r2:   {r2_score(y_test, predictions):.4f}\")",
            "print(f\"mae:  {mean_absolute_error(y_test, predictions):.4f}\")",
            "print(f\"rmse: {mean_squared_error(y_test, predictions) ** 0.5:.4f}\")",
        ]
        if workflow_kind == KIND_TIMESERIES_FORECAST:
            lines.append("errors = [abs(a - p) / abs(a) for a, p in zip(y_test, predictions) if a != 0]")
            lines.append("print(f\"mape: {100 * sum(errors) / len(errors):.4f}%\" if errors else \"mape: undefined, every actual value is zero\")")
    blocks.append(Block(heading(STEP_EVALUATE, "score the model on the rows it never saw"), lines))
    return imports, blocks

def _header(workflow, kind: str) -> str:
    needs = "pip install openai" if kind == KIND_LLM_PLAYGROUND else "pip install pandas scikit-learn"
    return "\n".join([
        '"""',
        f"{workflow.name} — generated by Crescent Forge.",
        "",
        "Each block below is one step from the workflow canvas, in the order the pipeline",
        "runs them. Edit it, break it, run it again: that is what it is for.",
        "",
        f"    {needs}",
        f"    python {_filename(workflow)}",
        '"""',
    ])

def _filename(workflow) -> str:
    safe = "".join(char if char.isalnum() else "_" for char in workflow.name).strip("_").lower() or "workflow"
    return f"{safe}.py"

def _blocks_for(workflow, steps, data_path: str, model: str) -> tuple[list[str], list[Block]]:
    steps = ordered_steps(steps)
    if not steps:
        raise ValueError("A workflow with no steps has nothing to generate.")
    if workflow.kind == KIND_LLM_PLAYGROUND:
        if steps[0].kind != STEP_PROMPT:
            raise ValueError("An LLM playground workflow needs its prompt step.")
        return _llm_blocks(steps, model)
    return _tabular_blocks(workflow.kind, steps, _target_name(steps, workflow.kind), data_path)

def generate_script(workflow, steps, *, data_path: str = "data.csv", model: str = "gpt-4o-mini") -> str:
    imports, blocks = _blocks_for(workflow, steps, data_path, model)
    parts = [_header(workflow, workflow.kind), "", *dict.fromkeys(imports), ""]
    for block in blocks:
        parts.append(f"# {block.heading}")
        parts.extend(block.lines)
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"

def generate_notebook(workflow, steps, *, data_path: str = "data.csv", model: str = "gpt-4o-mini") -> dict:
    """Same blocks, one cell each, so the learner can run a step and look at it before
    running the next one."""
    imports, blocks = _blocks_for(workflow, steps, data_path, model)
    cells = [
        {"cell_type": "markdown", "metadata": {}, "source": [f"# {workflow.name}\n", "\n", "Generated by Crescent Forge. One cell per step of the workflow.\n"]},
        {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": _source(list(dict.fromkeys(imports)))},
    ]
    for block in blocks:
        cells.append({"cell_type": "markdown", "metadata": {}, "source": [block.heading]})
        cells.append({"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": _source(block.lines)})
    return {
        "cells": cells,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}, "language_info": {"name": "python"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }

def _source(lines: list[str]) -> list[str]:
    return [line + "\n" for line in lines[:-1]] + lines[-1:] if lines else []

def script_filename(workflow) -> str:
    return _filename(workflow)

def notebook_filename(workflow) -> str:
    return _filename(workflow)[:-3] + ".ipynb"
