"""Runs a tabular or forecast workflow: CSV in, fitted model and metrics out.

Every failure a learner can cause is caught here and turned into a sentence they can act
on. A traceback is a message about Forge's internals, and it is never what comes back.
"""
import io
import json
import logging
import math
from app.config import settings
from app.models import KIND_TABULAR_CLASSIFICATION, KIND_TIMESERIES_FORECAST
from app.services.steps import STEP_ENCODE_CATEGORICAL, STEP_EVALUATE, STEP_HANDLE_MISSING, STEP_LAG_FEATURES, STEP_LOAD_CSV, STEP_SCALE_FEATURES, STEP_SELECT_FEATURES, STEP_SELECT_TARGET, STEP_TRAIN_MODEL, STEP_TRAIN_TEST_SPLIT, ordered_steps

logger = logging.getLogger(__name__)

# Above this many distinct values a classification target is almost certainly a
# measurement, and the learner has picked the wrong column rather than built a model with
# 900 classes.
MAX_CLASSES = 50
SAMPLE_PREDICTIONS = 20

class ExecutionError(Exception):
    """Message written for the learner. Stored on the run row as-is."""

def _params(step) -> dict:
    return json.loads(step.params or "{}")

def _build_estimator(algorithm: str, hyperparameters: dict):
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.linear_model import LinearRegression, LogisticRegression, Ridge
    from sklearn.tree import DecisionTreeClassifier

    factories = {
        "logistic_regression": lambda kw: LogisticRegression(max_iter=kw.pop("max_iter", 1000), **kw),
        "random_forest_classifier": lambda kw: RandomForestClassifier(**({"n_estimators": 100, "random_state": 42} | kw)),
        "decision_tree_classifier": lambda kw: DecisionTreeClassifier(**({"random_state": 42} | kw)),
        "linear_regression": lambda kw: LinearRegression(),
        "ridge": lambda kw: Ridge(**kw),
        "random_forest_regressor": lambda kw: RandomForestRegressor(**({"n_estimators": 100, "random_state": 42} | kw)),
    }
    return factories[algorithm](dict(hyperparameters))

def _read_csv(csv_text: str):
    import pandas as pd

    try:
        frame = pd.read_csv(io.StringIO(csv_text))
    except Exception as exc:
        logger.warning("pandas could not read the dataset: %s", exc)
        raise ExecutionError("The dataset could not be read as a table. Check every row has the same number of commas.")
    if frame.empty or not len(frame.columns):
        raise ExecutionError("The dataset has no rows to learn from.")
    if len(frame) > settings.MAX_TRAIN_ROWS:
        raise ExecutionError(f"This dataset has {len(frame):,} rows and Forge trains on up to {settings.MAX_TRAIN_ROWS:,}. Take a sample and upload that.")
    return frame

def _check_size(frame) -> None:
    cells = len(frame) * len(frame.columns)
    if cells > settings.MAX_TRAIN_CELLS:
        raise ExecutionError(f"After preparation this is {len(frame):,} rows by {len(frame.columns):,} columns, past the {settings.MAX_TRAIN_CELLS:,} cells Forge can hold. Choose fewer features, or use ordinal encoding instead of one-hot.")

def _require_column(frame, column: str, what: str) -> None:
    if column not in frame.columns:
        available = ", ".join(str(c) for c in list(frame.columns)[:15])
        raise ExecutionError(f"There is no column called '{column}' to use as the {what}. The dataset has: {available}.")
    if frame[column].isna().all():
        raise ExecutionError(f"Column '{column}' is empty in every row, so it cannot be the {what}.")

def _apply_missing(frame, params: dict):
    columns = [c for c in (params.get("columns") or list(frame.columns)) if c in frame.columns]
    strategy = params.get("strategy", "drop_rows")
    if strategy == "drop_rows":
        return frame.dropna(subset=columns)
    if strategy == "constant":
        return frame.fillna({c: params.get("fill_value") for c in columns})
    filled = frame.copy()
    for column in columns:
        series = filled[column]
        if strategy == "most_frequent" or series.dtype == object:
            modes = series.mode(dropna=True)
            if len(modes):
                filled[column] = series.fillna(modes.iloc[0])
        else:
            value = series.mean() if strategy == "mean" else series.median()
            if value == value:  # NaN mean means the column is empty; leave it for the target check
                filled[column] = series.fillna(value)
    return filled

def _apply_encoding(frame, params: dict, target: str | None):
    import pandas as pd

    requested = params.get("columns") or []
    text_columns = [c for c in frame.columns if frame[c].dtype == object and c != target]
    columns = [c for c in requested if c in frame.columns and c != target] or ([] if requested else text_columns)
    if not columns:
        return frame
    if params.get("strategy", "one_hot") == "ordinal":
        encoded = frame.copy()
        for column in columns:
            encoded[column] = encoded[column].astype("category").cat.codes
        return encoded
    encoded = pd.get_dummies(frame, columns=columns, dummy_na=False)
    _check_size(encoded)
    return encoded

def _apply_lags(frame, params: dict):
    column, lags, horizon = params["column"], params["lags"], params["horizon"]
    _require_column(frame, column, "value to forecast")
    import pandas as pd

    series = pd.to_numeric(frame[column], errors="coerce")
    if series.notna().sum() < lags + horizon + settings.MIN_TRAIN_ROWS:
        raise ExecutionError(f"Column '{column}' has too few numbers to forecast from: {lags} lags plus a {horizon}-step horizon needs at least {lags + horizon + settings.MIN_TRAIN_ROWS} readings.")
    built = pd.DataFrame({f"{column}_lag_{i}": series.shift(i) for i in range(1, lags + 1)})
    built[f"{column}_t_plus_{horizon}"] = series.shift(-horizon + 1) if horizon > 1 else series
    return built.dropna().reset_index(drop=True)

def _target_name(steps, kind: str) -> str:
    for step in steps:
        if step.kind == STEP_SELECT_TARGET:
            return _params(step)["column"]
        if step.kind == STEP_LAG_FEATURES and kind == KIND_TIMESERIES_FORECAST:
            params = _params(step)
            return f"{params['column']}_t_plus_{params['horizon']}"
    raise ExecutionError("This workflow never says which column to predict. Add a 'select_target' step.")

def _classification_metrics(y_test, predictions) -> tuple[dict, dict]:
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score

    labels = sorted({str(v) for v in list(y_test) + list(predictions)})
    metrics = {
        "accuracy": round(float(accuracy_score(y_test, predictions)), 4),
        "precision_macro": round(float(precision_score(y_test, predictions, average="macro", zero_division=0)), 4),
        "recall_macro": round(float(recall_score(y_test, predictions, average="macro", zero_division=0)), 4),
        "f1_macro": round(float(f1_score(y_test, predictions, average="macro", zero_division=0)), 4),
    }
    matrix = confusion_matrix(y_test.astype(str), [str(p) for p in predictions], labels=labels)
    return metrics, {"class_labels": labels, "confusion_matrix": [[int(v) for v in row] for row in matrix]}

def _regression_metrics(y_test, predictions, *, timeseries: bool) -> tuple[dict, dict]:
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    mse = float(mean_squared_error(y_test, predictions))
    metrics = {
        "r2": round(float(r2_score(y_test, predictions)), 4),
        "mae": round(float(mean_absolute_error(y_test, predictions)), 4),
        "rmse": round(math.sqrt(mse), 4),
    }
    if timeseries:
        actual = [float(v) for v in y_test]
        errors = [abs(a - float(p)) / abs(a) for a, p in zip(actual, predictions, strict=True) if a != 0]
        # Undefined when every actual is zero, and a missing figure is better than a
        # divide-by-zero dressed up as a score.
        metrics["mape_percent"] = round(100 * sum(errors) / len(errors), 4) if errors else None
    return metrics, {}

def run_tabular(kind: str, csv_text: str, steps) -> tuple[dict, dict]:
    """Returns (metrics, result). Raises ExecutionError with learner-readable text."""
    steps = ordered_steps(steps)
    frame = _read_csv(csv_text)
    target = _target_name(steps, kind)
    split_params = {"test_size": 0.2, "random_state": 42, "shuffle": kind != KIND_TIMESERIES_FORECAST}
    feature_columns: list[str] = []
    scale_params: dict | None = None
    model_params: dict | None = None

    for step in steps:
        params = _params(step)
        if step.kind == STEP_LOAD_CSV or step.kind == STEP_EVALUATE:
            continue
        if step.kind == STEP_LAG_FEATURES:
            frame = _apply_lags(frame, params)
        elif step.kind == STEP_HANDLE_MISSING:
            frame = _apply_missing(frame, params)
        elif step.kind == STEP_ENCODE_CATEGORICAL:
            frame = _apply_encoding(frame, params, target)
        elif step.kind == STEP_SELECT_TARGET:
            _require_column(frame, target, "target")
        elif step.kind == STEP_SELECT_FEATURES:
            feature_columns = [c for c in params.get("columns") or [] if c != target]
        elif step.kind == STEP_TRAIN_TEST_SPLIT:
            split_params = params
        elif step.kind == STEP_SCALE_FEATURES:
            scale_params = params
        elif step.kind == STEP_TRAIN_MODEL:
            model_params = params

    _require_column(frame, target, "target")
    if feature_columns:
        missing = [c for c in feature_columns if c not in frame.columns]
        if missing:
            raise ExecutionError(f"These feature columns are not in the prepared table: {', '.join(missing)}. One-hot encoding renames text columns, so pick the encoded names or leave features empty to use them all.")
    else:
        feature_columns = [c for c in frame.columns if c != target]
    if not feature_columns:
        raise ExecutionError("There are no feature columns left to learn from once the target is removed.")

    features = frame[feature_columns]
    non_numeric = [c for c in feature_columns if features[c].dtype == object]
    if non_numeric:
        raise ExecutionError(f"These feature columns are still text: {', '.join(non_numeric[:10])}. Add an 'encode_categorical' step so the model can read them.")
    usable = frame[feature_columns + [target]].dropna()
    if len(usable) < settings.MIN_TRAIN_ROWS:
        raise ExecutionError(f"Only {len(usable)} complete rows are left after preparation and Forge needs at least {settings.MIN_TRAIN_ROWS}. Try filling missing values instead of dropping rows.")
    _check_size(usable)
    features, labels = usable[feature_columns], usable[target]

    if kind == KIND_TABULAR_CLASSIFICATION:
        classes = labels.nunique()
        if classes < 2:
            raise ExecutionError(f"Every row has the same value in '{target}', so there is nothing to tell apart.")
        if classes > MAX_CLASSES:
            raise ExecutionError(f"'{target}' has {classes} different values. That looks like a measurement rather than a category, so try a regression workflow instead.")
    else:
        import pandas as pd

        labels = pd.to_numeric(labels, errors="coerce")
        if labels.isna().any():
            raise ExecutionError(f"'{target}' has values that are not numbers, so it cannot be predicted by a regression. Use a classification workflow, or clean the column.")

    if model_params is None:
        raise ExecutionError("This workflow has no 'train_model' step, so there is nothing to run.")

    from sklearn.model_selection import train_test_split

    stratify = labels if kind == KIND_TABULAR_CLASSIFICATION and split_params.get("shuffle", True) and labels.value_counts().min() >= 2 else None
    x_train, x_test, y_train, y_test = train_test_split(
        features, labels,
        test_size=split_params.get("test_size", 0.2),
        random_state=split_params.get("random_state", 42),
        shuffle=split_params.get("shuffle", True),
        stratify=stratify,
    )
    if not len(x_test):
        raise ExecutionError("The test split came out empty. Raise 'test_size' or use more rows.")

    if scale_params is not None:
        from sklearn.preprocessing import MinMaxScaler, StandardScaler

        scaler = MinMaxScaler() if scale_params.get("strategy") == "minmax" else StandardScaler()
        # Fitted on the training rows only: a scaler fitted on everything has already read
        # the test set, and the score would be flattering rather than honest.
        x_train = scaler.fit_transform(x_train)
        x_test = scaler.transform(x_test)

    model = _build_estimator(model_params["algorithm"], model_params.get("hyperparameters") or {})
    try:
        model.fit(x_train, y_train)
    except Exception as exc:
        logger.warning("fit failed for %s: %s", model_params["algorithm"], exc)
        raise ExecutionError(f"The model could not be trained on this data ({exc.__class__.__name__}). Check the feature columns are numbers and that enough rows are left after preparation.")
    predictions = model.predict(x_test)

    if kind == KIND_TABULAR_CLASSIFICATION:
        metrics, extra = _classification_metrics(y_test, predictions)
    else:
        metrics, extra = _regression_metrics(y_test, predictions, timeseries=kind == KIND_TIMESERIES_FORECAST)

    result = {
        "target": target,
        "features": feature_columns,
        "algorithm": model_params["algorithm"],
        "hyperparameters": model_params.get("hyperparameters") or {},
        "rows_used": int(len(usable)),
        "train_rows": int(len(y_train)),
        "test_rows": int(len(y_test)),
        "scaled": scale_params is not None,
        "predictions_sample": [
            {"actual": _plain(a), "predicted": _plain(p)}
            for a, p in list(zip(list(y_test), list(predictions), strict=True))[:SAMPLE_PREDICTIONS]
        ],
        **extra,
    }
    return metrics, result

def _plain(value):
    """numpy scalars are not JSON-serialisable, and the run row is JSON."""
    item = getattr(value, "item", None)
    value = item() if callable(item) else value
    return round(value, 6) if isinstance(value, float) else value
