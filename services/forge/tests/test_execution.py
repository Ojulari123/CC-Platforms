import json
import pytest
from app.models import WorkflowStep
from app.services.execution import ExecutionError, run_tabular

def steps(*pairs):
    return [WorkflowStep(position=i, kind=kind, params=json.dumps(params)) for i, (kind, params) in enumerate(pairs)]

def classification_csv(rows=60):
    lines = ["hours,attendance,grade"]
    for i in range(rows):
        passing = i % 2 == 0
        lines.append(f"{20 + i if passing else 2 + i % 5},{90 - i % 5 if passing else 40 + i % 5},{'pass' if passing else 'fail'}")
    return "\n".join(lines) + "\n"

def regression_csv(rows=60):
    return "size,price\n" + "\n".join(f"{50 + i},{100000 + 1500 * i}" for i in range(rows)) + "\n"

def series_csv(rows=60):
    return "month,sales\n" + "\n".join(f"2020-{i % 12 + 1:02d},{1000 + 10 * i + (i % 4) * 25}" for i in range(rows)) + "\n"

BASE_TAIL = (("train_test_split", {"test_size": 0.25, "random_state": 3, "shuffle": True}), ("evaluate", {}))

def test_classification_reports_the_metrics_a_learner_should_see():
    metrics, result = run_tabular("tabular_classification", classification_csv(), steps(
        ("load_csv", {}),
        ("select_target", {"column": "grade"}),
        ("train_model", {"algorithm": "random_forest_classifier", "hyperparameters": {"n_estimators": 20}}),
        *BASE_TAIL,
    ))
    assert set(metrics) == {"accuracy", "precision_macro", "recall_macro", "f1_macro"}
    assert metrics["accuracy"] == 1.0
    assert result["class_labels"] == ["fail", "pass"]
    assert len(result["confusion_matrix"]) == 2
    assert result["target"] == "grade"
    assert result["features"] == ["hours", "attendance"]
    assert result["train_rows"] + result["test_rows"] == result["rows_used"] == 60
    assert result["predictions_sample"][0].keys() == {"actual", "predicted"}

def test_regression_reports_r2_mae_and_rmse():
    metrics, result = run_tabular("tabular_regression", regression_csv(), steps(
        ("load_csv", {}),
        ("select_target", {"column": "price"}),
        ("scale_features", {"strategy": "minmax"}),
        ("train_model", {"algorithm": "linear_regression"}),
        *BASE_TAIL,
    ))
    assert set(metrics) == {"r2", "mae", "rmse"}
    assert metrics["r2"] > 0.99
    assert result["scaled"] is True

def test_forecast_adds_mape_and_builds_its_own_target():
    metrics, result = run_tabular("timeseries_forecast", series_csv(), steps(
        ("load_csv", {}),
        ("lag_features", {"column": "sales", "lags": 4, "horizon": 1}),
        ("train_test_split", {"test_size": 0.2, "random_state": 1, "shuffle": False}),
        ("train_model", {"algorithm": "ridge", "hyperparameters": {"alpha": 0.5}}),
        ("evaluate", {}),
    ))
    assert "mape_percent" in metrics
    assert result["target"] == "sales_t_plus_1"
    assert result["features"] == ["sales_lag_1", "sales_lag_2", "sales_lag_3", "sales_lag_4"]

def test_one_hot_encoding_turns_text_into_columns():
    csv = "city,size,price\n" + "\n".join(f"{'lagos' if i % 2 else 'abuja'},{40 + i},{90000 + 800 * i}" for i in range(40)) + "\n"
    _, result = run_tabular("tabular_regression", csv, steps(
        ("load_csv", {}),
        ("select_target", {"column": "price"}),
        ("encode_categorical", {"strategy": "one_hot", "columns": []}),
        ("train_model", {"algorithm": "linear_regression"}),
        *BASE_TAIL,
    ))
    assert result["features"] == ["size", "city_abuja", "city_lagos"]

def test_ordinal_encoding_keeps_one_column():
    csv = "city,size,price\n" + "\n".join(f"{'lagos' if i % 2 else 'abuja'},{40 + i},{90000 + 800 * i}" for i in range(40)) + "\n"
    _, result = run_tabular("tabular_regression", csv, steps(
        ("load_csv", {}),
        ("select_target", {"column": "price"}),
        ("encode_categorical", {"strategy": "ordinal", "columns": ["city"]}),
        ("train_model", {"algorithm": "linear_regression"}),
        *BASE_TAIL,
    ))
    assert result["features"] == ["city", "size"]

@pytest.mark.parametrize("strategy", ["mean", "median", "most_frequent", "drop_rows"])
def test_missing_values_are_handled_by_the_chosen_strategy(strategy):
    rows = [f"{50 + i},{'' if i == 3 else 100000 + 900 * i}" for i in range(40)]
    csv = "size,price\n" + "\n".join(rows) + "\n"
    _, result = run_tabular("tabular_regression", csv, steps(
        ("load_csv", {}),
        ("select_target", {"column": "price"}),
        ("handle_missing", {"strategy": strategy, "columns": ["price"]}),
        ("train_model", {"algorithm": "linear_regression"}),
        *BASE_TAIL,
    ))
    assert result["rows_used"] == (39 if strategy == "drop_rows" else 40)

def test_constant_fill_keeps_every_row():
    csv = "size,price\n" + "\n".join(f"{50 + i},{'' if i == 3 else 100000 + 900 * i}" for i in range(40)) + "\n"
    _, result = run_tabular("tabular_regression", csv, steps(
        ("load_csv", {}),
        ("select_target", {"column": "price"}),
        ("handle_missing", {"strategy": "constant", "fill_value": 0, "columns": ["price"]}),
        ("train_model", {"algorithm": "linear_regression"}),
        *BASE_TAIL,
    ))
    assert result["rows_used"] == 40

def test_chosen_features_are_the_only_ones_used():
    csv = "a,b,c,price\n" + "\n".join(f"{i},{i * 2},{i * 3},{1000 + i}" for i in range(40)) + "\n"
    _, result = run_tabular("tabular_regression", csv, steps(
        ("load_csv", {}),
        ("select_target", {"column": "price"}),
        ("select_features", {"columns": ["a", "c"]}),
        ("train_model", {"algorithm": "ridge"}),
        *BASE_TAIL,
    ))
    assert result["features"] == ["a", "c"]

def _error(kind, csv, *pairs):
    with pytest.raises(ExecutionError) as excinfo:
        run_tabular(kind, csv, steps(*pairs))
    message = str(excinfo.value)
    assert "Traceback" not in message and "  File " not in message
    return message

def test_empty_csv_says_so():
    assert "no rows to learn from" in _error("tabular_regression", "size,price\n", ("load_csv", {}), ("select_target", {"column": "price"}), ("train_model", {"algorithm": "ridge"}), *BASE_TAIL)

def test_missing_target_column_lists_what_is_there():
    message = _error("tabular_regression", regression_csv(), ("load_csv", {}), ("select_target", {"column": "revenue"}), ("train_model", {"algorithm": "ridge"}), *BASE_TAIL)
    assert "no column called 'revenue'" in message and "size, price" in message

def test_all_null_target_column_says_so():
    csv = "size,price\n" + "\n".join(f"{50 + i}," for i in range(40)) + "\n"
    assert "empty in every row" in _error("tabular_regression", csv, ("load_csv", {}), ("select_target", {"column": "price"}), ("train_model", {"algorithm": "ridge"}), *BASE_TAIL)

def test_too_many_rows_is_refused_before_training(monkeypatch):
    monkeypatch.setattr("app.config.settings.MAX_TRAIN_ROWS", 10)
    message = _error("tabular_regression", regression_csv(), ("load_csv", {}), ("select_target", {"column": "price"}), ("train_model", {"algorithm": "ridge"}), *BASE_TAIL)
    assert "Take a sample" in message

def test_too_wide_after_encoding_is_refused(monkeypatch):
    monkeypatch.setattr("app.config.settings.MAX_TRAIN_CELLS", 50)
    csv = "city,size,price\n" + "\n".join(f"city_{i},{40 + i},{9000 + i}" for i in range(40)) + "\n"
    message = _error("tabular_regression", csv, ("load_csv", {}), ("select_target", {"column": "price"}), ("encode_categorical", {"strategy": "one_hot", "columns": []}), ("train_model", {"algorithm": "ridge"}), *BASE_TAIL)
    assert "ordinal encoding" in message

def test_too_few_rows_left_after_dropping_says_what_to_try():
    csv = "size,price\n" + "\n".join(f"{50 + i},{'' if i > 2 else 1000 + i}" for i in range(40)) + "\n"
    message = _error("tabular_regression", csv, ("load_csv", {}), ("select_target", {"column": "price"}), ("handle_missing", {"strategy": "drop_rows", "columns": ["price"]}), ("train_model", {"algorithm": "ridge"}), *BASE_TAIL)
    assert "filling missing values" in message

def test_unencoded_text_feature_points_at_the_fix():
    csv = "city,size,price\n" + "\n".join(f"{'lagos' if i % 2 else 'abuja'},{40 + i},{9000 + i}" for i in range(40)) + "\n"
    message = _error("tabular_regression", csv, ("load_csv", {}), ("select_target", {"column": "price"}), ("train_model", {"algorithm": "ridge"}), *BASE_TAIL)
    assert "encode_categorical" in message

def test_single_class_target_says_there_is_nothing_to_tell_apart():
    csv = "hours,grade\n" + "\n".join(f"{i},pass" for i in range(40)) + "\n"
    assert "nothing to tell apart" in _error("tabular_classification", csv, ("load_csv", {}), ("select_target", {"column": "grade"}), ("train_model", {"algorithm": "logistic_regression"}), *BASE_TAIL)

def test_continuous_target_in_a_classification_suggests_regression():
    csv = "a,price\n" + "\n".join(f"{i},{1000 + i}" for i in range(80)) + "\n"
    assert "try a regression workflow" in _error("tabular_classification", csv, ("load_csv", {}), ("select_target", {"column": "price"}), ("train_model", {"algorithm": "logistic_regression"}), *BASE_TAIL)

def test_text_target_in_a_regression_says_so():
    csv = "a,grade\n" + "\n".join(f"{i},{'pass' if i % 2 else 'fail'}" for i in range(40)) + "\n"
    assert "not numbers" in _error("tabular_regression", csv, ("load_csv", {}), ("select_target", {"column": "grade"}), ("train_model", {"algorithm": "ridge"}), *BASE_TAIL)

def test_feature_name_that_survived_no_encoding_is_named():
    csv = "city,size,price\n" + "\n".join(f"{'lagos' if i % 2 else 'abuja'},{40 + i},{9000 + i}" for i in range(40)) + "\n"
    message = _error("tabular_regression", csv, ("load_csv", {}), ("select_target", {"column": "price"}), ("encode_categorical", {"strategy": "one_hot", "columns": []}), ("select_features", {"columns": ["city"]}), ("train_model", {"algorithm": "ridge"}), *BASE_TAIL)
    assert "One-hot encoding renames" in message

def test_series_too_short_to_forecast_says_how_short():
    csv = "month,sales\n" + "\n".join(f"2020-{i + 1:02d},{100 + i}" for i in range(8)) + "\n"
    assert "too few numbers to forecast" in _error("timeseries_forecast", csv, ("load_csv", {}), ("lag_features", {"column": "sales", "lags": 4, "horizon": 1}), ("train_model", {"algorithm": "ridge"}), *BASE_TAIL)

def test_a_malformed_csv_is_a_sentence_not_a_parser_error():
    assert "same number of commas" in _error("tabular_regression", 'a,b\n"unclosed,1\n2,3,4,5,6\n', ("load_csv", {}), ("select_target", {"column": "b"}), ("train_model", {"algorithm": "ridge"}), *BASE_TAIL)
