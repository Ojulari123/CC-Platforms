"""The step vocabulary: the one place that says what a canvas step can be.

Both weeks hang off this. The UI renders a step from its kind and params, the execution
engine switches on the same kind, and the code generator emits a line of Python per kind.
Anything not described here cannot be stored, so the three surfaces cannot drift.
"""
from app.models import KIND_IMAGE_CLASSIFICATION, KIND_LLM_PLAYGROUND, KIND_LLM_VISION, KIND_TABULAR_CLASSIFICATION, KIND_TABULAR_REGRESSION, KIND_TIMESERIES_FORECAST

STEP_LOAD_CSV = "load_csv"
STEP_HANDLE_MISSING = "handle_missing"
STEP_ENCODE_CATEGORICAL = "encode_categorical"
STEP_SCALE_FEATURES = "scale_features"
STEP_SELECT_FEATURES = "select_features"
STEP_SELECT_TARGET = "select_target"
STEP_LAG_FEATURES = "lag_features"
STEP_TRAIN_TEST_SPLIT = "train_test_split"
STEP_TRAIN_MODEL = "train_model"
STEP_EVALUATE = "evaluate"
STEP_PROMPT = "prompt"
STEP_LOAD_IMAGES = "load_images"
STEP_RESIZE_IMAGES = "resize_images"
STEP_GRAYSCALE_IMAGES = "grayscale_images"
STEP_FLATTEN_IMAGES = "flatten_images"
STEP_VISION_PROMPT = "vision_prompt"

# Every image in a dataset has to end up the same length once flattened, so the resize is
# what makes the rows line up rather than an optional tidy-up. The ceiling is low on
# purpose: 64x64 in colour is already 12,288 numbers per image.
MIN_IMAGE_EDGE = 8
MAX_IMAGE_EDGE = 64

# What an image workflow asks the vision model when the learner has not written their own
# question. Captioning is the default; the prompt box is what turns it into Q&A.
DEFAULT_CAPTION_PROMPT = "Describe this image in two or three sentences."
DEFAULT_CAPTION_SYSTEM = "You describe images plainly and only say what you can actually see."

MISSING_STRATEGIES = ("drop_rows", "mean", "median", "most_frequent", "constant")
ENCODE_STRATEGIES = ("one_hot", "ordinal")
SCALE_STRATEGIES = ("standard", "minmax")

CLASSIFIER_ALGORITHMS = ("logistic_regression", "random_forest_classifier", "decision_tree_classifier")
REGRESSOR_ALGORITHMS = ("linear_regression", "ridge", "random_forest_regressor")

# Which algorithms a workflow of each kind may pick. A forecast is a regression on lagged
# columns, so it shares the regressor list.
ALGORITHMS_FOR_KIND = {
    KIND_TABULAR_CLASSIFICATION: CLASSIFIER_ALGORITHMS,
    KIND_TABULAR_REGRESSION: REGRESSOR_ALGORITHMS,
    KIND_TIMESERIES_FORECAST: REGRESSOR_ALGORITHMS,
    KIND_IMAGE_CLASSIFICATION: CLASSIFIER_ALGORITHMS,
}

TABULAR_STEPS = (
    STEP_LOAD_CSV, STEP_HANDLE_MISSING, STEP_ENCODE_CATEGORICAL, STEP_SCALE_FEATURES,
    STEP_SELECT_FEATURES, STEP_SELECT_TARGET, STEP_TRAIN_TEST_SPLIT, STEP_TRAIN_MODEL, STEP_EVALUATE,
)
IMAGE_STEPS = (
    STEP_LOAD_IMAGES, STEP_RESIZE_IMAGES, STEP_GRAYSCALE_IMAGES, STEP_FLATTEN_IMAGES,
    STEP_SCALE_FEATURES, STEP_TRAIN_TEST_SPLIT, STEP_TRAIN_MODEL, STEP_EVALUATE,
)
STEPS_FOR_KIND = {
    KIND_TABULAR_CLASSIFICATION: TABULAR_STEPS,
    KIND_TABULAR_REGRESSION: TABULAR_STEPS,
    KIND_TIMESERIES_FORECAST: TABULAR_STEPS + (STEP_LAG_FEATURES,),
    KIND_IMAGE_CLASSIFICATION: IMAGE_STEPS,
    KIND_LLM_PLAYGROUND: (STEP_PROMPT,),
    KIND_LLM_VISION: (STEP_VISION_PROMPT,),
}

# Said in the UI beside an image workflow, and worth saying plainly. Flattened pixels are
# a real technique and a weak one: the model sees a list of numbers with no idea which
# were next to each other, so a subject shifted a few pixels looks like different data.
FLATTENED_PIXEL_CAVEAT = (
    "Flattening throws away where each pixel was. The model sees a list of numbers and "
    "cannot tell that two of them were side by side, so it learns colour and position "
    "rather than shape, and it does not cope with a subject that moves or rotates. "
    "This is here to show the pipeline end to end. A convolutional network is what real "
    "image classification uses, and it would score far higher on the same photos."
)

# Shown in the UI beside each step so the choice is visible rather than hidden behind Run.
STEP_CATALOG = [
    {"kind": STEP_LOAD_CSV, "label": "Load CSV", "summary": "Read the dataset attached to this workflow into a table.", "params": {}},
    {"kind": STEP_HANDLE_MISSING, "label": "Handle missing values", "summary": "Drop rows with gaps, or fill them.", "params": {"strategy": list(MISSING_STRATEGIES), "columns": "list of column names, empty means every column", "fill_value": "used by the constant strategy"}},
    {"kind": STEP_ENCODE_CATEGORICAL, "label": "Encode categories", "summary": "Turn text columns into numbers a model can read.", "params": {"strategy": list(ENCODE_STRATEGIES), "columns": "list of column names, empty means every text column"}},
    {"kind": STEP_SCALE_FEATURES, "label": "Scale features", "summary": "Put numeric columns on a comparable range.", "params": {"strategy": list(SCALE_STRATEGIES), "columns": "list of column names, empty means every numeric feature"}},
    {"kind": STEP_SELECT_FEATURES, "label": "Choose features", "summary": "The columns the model learns from. Empty means everything except the target.", "params": {"columns": "list of column names"}},
    {"kind": STEP_SELECT_TARGET, "label": "Choose target", "summary": "The column the model predicts.", "params": {"column": "one column name"}},
    {"kind": STEP_LAG_FEATURES, "label": "Build lag features", "summary": "Turn a time series into a table: each row predicts from the previous values.", "params": {"column": "the value column", "lags": "how many previous steps, e.g. 3", "horizon": "how many steps ahead to predict"}},
    {"kind": STEP_TRAIN_TEST_SPLIT, "label": "Split train and test", "summary": "Hold some rows back so the score is measured on data the model never saw.", "params": {"test_size": "0.1 to 0.5", "random_state": "integer, keeps the split repeatable", "shuffle": "false for time series"}},
    {"kind": STEP_TRAIN_MODEL, "label": "Train model", "summary": "Fit the chosen algorithm on the training rows.", "params": {"algorithm": {"classification": list(CLASSIFIER_ALGORITHMS), "regression": list(REGRESSOR_ALGORITHMS)}, "hyperparameters": "algorithm settings, e.g. n_estimators"}},
    {"kind": STEP_EVALUATE, "label": "Evaluate", "summary": "Score the trained model on the held-back rows.", "params": {}},
    {"kind": STEP_LOAD_IMAGES, "label": "Load images", "summary": "Read the image archive attached to this workflow. Each top-level folder is one class.", "params": {}},
    {"kind": STEP_RESIZE_IMAGES, "label": "Resize", "summary": "Shrink every image to the same size. Required: the model needs every row the same length.", "params": {"width": f"{MIN_IMAGE_EDGE} to {MAX_IMAGE_EDGE}", "height": f"{MIN_IMAGE_EDGE} to {MAX_IMAGE_EDGE}"}},
    {"kind": STEP_GRAYSCALE_IMAGES, "label": "Grayscale", "summary": "Drop colour. One number per pixel instead of three, so a third of the features.", "params": {}},
    {"kind": STEP_FLATTEN_IMAGES, "label": "Flatten to a feature vector", "summary": "Lay the pixel grid out as one long row. Required, and it is what makes this weaker than a convolutional network: position is lost.", "params": {}},
    {"kind": STEP_VISION_PROMPT, "label": "Ask about an image", "summary": "Send one image to the vision model, with your own question or a request for a caption.", "params": {"image": "the name of an image in the attached dataset", "system": "how the model should behave", "prompt": "your question, or leave the default to get a caption", "max_tokens": "reply length ceiling"}},
    {"kind": STEP_PROMPT, "label": "Prompt", "summary": "Send instructions and your own text to the language model.", "params": {"system": "how the model should behave", "prompt": "your question", "context": "optional text the answer must come from", "max_tokens": "reply length ceiling"}},
]

# Hyperparameters a learner may set, and what they must be. Anything else is refused
# rather than passed through, because both the trainer and the generated script hand
# these straight to scikit-learn.
ALLOWED_HYPERPARAMETERS = {
    "n_estimators": int,
    "max_depth": int,
    "min_samples_leaf": int,
    "max_iter": int,
    "C": float,
    "alpha": float,
    "random_state": int,
}

class StepError(ValueError):
    """A message written for the learner. Callers turn it into a 400 or a run error."""

def _as_list(value, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise StepError(f"'{field}' must be a list of column names.")
    return value

def _one_of(value, allowed, field: str) -> str:
    if value not in allowed:
        raise StepError(f"'{field}' must be one of {', '.join(allowed)}. Got {value!r}.")
    return value

def validate_step(workflow_kind: str, kind: str, params: dict) -> dict:
    """Returns the cleaned params, or raises StepError with something a learner can fix."""
    allowed = STEPS_FOR_KIND.get(workflow_kind)
    if allowed is None:
        raise StepError(f"Unknown workflow kind {workflow_kind!r}.")
    if kind not in allowed:
        raise StepError(f"A {workflow_kind.replace('_', ' ')} workflow has no '{kind}' step. Allowed: {', '.join(allowed)}.")
    if not isinstance(params, dict):
        raise StepError(f"Parameters for '{kind}' must be an object.")

    if kind == STEP_HANDLE_MISSING:
        strategy = _one_of(params.get("strategy", "drop_rows"), MISSING_STRATEGIES, "strategy")
        cleaned = {"strategy": strategy, "columns": _as_list(params.get("columns"), "columns")}
        if strategy == "constant":
            if "fill_value" not in params:
                raise StepError("The constant strategy needs a 'fill_value' to fill gaps with.")
            cleaned["fill_value"] = params["fill_value"]
        return cleaned
    if kind == STEP_ENCODE_CATEGORICAL:
        return {"strategy": _one_of(params.get("strategy", "one_hot"), ENCODE_STRATEGIES, "strategy"), "columns": _as_list(params.get("columns"), "columns")}
    if kind == STEP_SCALE_FEATURES:
        return {"strategy": _one_of(params.get("strategy", "standard"), SCALE_STRATEGIES, "strategy"), "columns": _as_list(params.get("columns"), "columns")}
    if kind == STEP_SELECT_FEATURES:
        return {"columns": _as_list(params.get("columns"), "columns")}
    if kind == STEP_SELECT_TARGET:
        column = params.get("column")
        if not isinstance(column, str) or not column.strip():
            raise StepError("Choose the column the model should predict.")
        return {"column": column}
    if kind == STEP_LAG_FEATURES:
        column = params.get("column")
        if not isinstance(column, str) or not column.strip():
            raise StepError("Choose the value column the forecast is built from.")
        lags = params.get("lags", 3)
        if not isinstance(lags, int) or isinstance(lags, bool) or not 1 <= lags <= 50:
            raise StepError("'lags' must be a whole number between 1 and 50.")
        horizon = params.get("horizon", 1)
        if not isinstance(horizon, int) or isinstance(horizon, bool) or not 1 <= horizon <= 50:
            raise StepError("'horizon' must be a whole number between 1 and 50.")
        return {"column": column, "lags": lags, "horizon": horizon}
    if kind == STEP_TRAIN_TEST_SPLIT:
        test_size = params.get("test_size", 0.2)
        if not isinstance(test_size, (int, float)) or isinstance(test_size, bool) or not 0.05 <= float(test_size) <= 0.5:
            raise StepError("'test_size' must be a fraction between 0.05 and 0.5, e.g. 0.2 for 20% held back.")
        random_state = params.get("random_state", 42)
        if not isinstance(random_state, int) or isinstance(random_state, bool):
            raise StepError("'random_state' must be a whole number.")
        return {"test_size": float(test_size), "random_state": random_state, "shuffle": bool(params.get("shuffle", True))}
    if kind == STEP_TRAIN_MODEL:
        algorithms = ALGORITHMS_FOR_KIND[workflow_kind]
        algorithm = _one_of(params.get("algorithm"), algorithms, "algorithm")
        raw = params.get("hyperparameters") or {}
        if not isinstance(raw, dict):
            raise StepError("'hyperparameters' must be an object, e.g. {\"n_estimators\": 100}.")
        hyperparameters = {}
        for name, value in raw.items():
            expected = ALLOWED_HYPERPARAMETERS.get(name)
            if expected is None:
                raise StepError(f"'{name}' is not a setting Forge passes to the model. Allowed: {', '.join(sorted(ALLOWED_HYPERPARAMETERS))}.")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise StepError(f"'{name}' must be a number.")
            hyperparameters[name] = expected(value)
        return {"algorithm": algorithm, "hyperparameters": hyperparameters}
    if kind == STEP_RESIZE_IMAGES:
        edges = {}
        for field in ("width", "height"):
            value = params.get(field, 32)
            if not isinstance(value, int) or isinstance(value, bool) or not MIN_IMAGE_EDGE <= value <= MAX_IMAGE_EDGE:
                raise StepError(f"'{field}' must be a whole number between {MIN_IMAGE_EDGE} and {MAX_IMAGE_EDGE} pixels. Bigger images turn into more numbers than this kind of model can use.")
            edges[field] = value
        return edges
    if kind == STEP_VISION_PROMPT:
        image = params.get("image")
        if not isinstance(image, str) or not image.strip():
            raise StepError("Choose which image in the dataset to ask about.")
        prompt = params.get("prompt") or DEFAULT_CAPTION_PROMPT
        if not isinstance(prompt, str) or not prompt.strip():
            raise StepError("Write the question you want to ask about the image, or leave it blank for a caption.")
        max_tokens = params.get("max_tokens", 300)
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or not 1 <= max_tokens <= 4000:
            raise StepError("'max_tokens' must be a whole number between 1 and 4000.")
        system = params.get("system") or DEFAULT_CAPTION_SYSTEM
        if not isinstance(system, str):
            raise StepError("'system' must be text.")
        return {"image": image, "system": system, "prompt": prompt, "max_tokens": max_tokens}
    if kind == STEP_PROMPT:
        prompt = params.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise StepError("Write the prompt you want to send.")
        max_tokens = params.get("max_tokens", 500)
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or not 1 <= max_tokens <= 4000:
            raise StepError("'max_tokens' must be a whole number between 1 and 4000.")
        context = params.get("context") or ""
        if not isinstance(context, str):
            raise StepError("'context' must be text.")
        system = params.get("system") or "You are a helpful assistant."
        if not isinstance(system, str):
            raise StepError("'system' must be text.")
        return {"system": system, "prompt": prompt, "context": context, "max_tokens": max_tokens}
    return {}

def validate_sequence(workflow_kind: str, steps: list[tuple[str, dict]]) -> list[dict]:
    """Order matters, so the sequence is checked as a whole and not step by step."""
    if not steps:
        raise StepError("A workflow needs at least one step.")
    cleaned = [validate_step(workflow_kind, kind, params) for kind, params in steps]
    kinds = [kind for kind, _ in steps]
    if workflow_kind == KIND_LLM_PLAYGROUND:
        if kinds != [STEP_PROMPT]:
            raise StepError("An LLM playground workflow is exactly one 'prompt' step.")
        return cleaned
    if workflow_kind == KIND_LLM_VISION:
        if kinds != [STEP_VISION_PROMPT]:
            raise StepError("An image question workflow is exactly one 'vision_prompt' step.")
        return cleaned
    if workflow_kind == KIND_IMAGE_CLASSIFICATION:
        return _validate_image_sequence(kinds, cleaned)
    if kinds[0] != STEP_LOAD_CSV:
        raise StepError("The first step must be 'load_csv'.")
    if kinds.count(STEP_LOAD_CSV) > 1:
        raise StepError("Only the first step can be 'load_csv'.")
    for required, why in ((STEP_TRAIN_MODEL, "train a model"), (STEP_EVALUATE, "evaluate it")):
        if required not in kinds:
            raise StepError(f"Add a '{required}' step: a run has to {why} to produce a result.")
    if kinds.index(STEP_EVALUATE) < kinds.index(STEP_TRAIN_MODEL):
        raise StepError("'evaluate' has to come after 'train_model'.")
    if workflow_kind == KIND_TIMESERIES_FORECAST:
        if STEP_LAG_FEATURES not in kinds:
            raise StepError("A forecast needs a 'lag_features' step: it is what turns the series into rows a model can learn from.")
    elif STEP_SELECT_TARGET not in kinds:
        raise StepError("Add a 'select_target' step: the model needs to know which column to predict.")
    return cleaned

def _validate_image_sequence(kinds: list[str], cleaned: list[dict]) -> list[dict]:
    if kinds[0] != STEP_LOAD_IMAGES:
        raise StepError("The first step must be 'load_images'.")
    if kinds.count(STEP_LOAD_IMAGES) > 1:
        raise StepError("Only the first step can be 'load_images'.")
    for kind in (STEP_RESIZE_IMAGES, STEP_GRAYSCALE_IMAGES, STEP_FLATTEN_IMAGES, STEP_SCALE_FEATURES, STEP_TRAIN_TEST_SPLIT, STEP_TRAIN_MODEL, STEP_EVALUATE):
        if kinds.count(kind) > 1:
            raise StepError(f"A workflow can only have one '{kind}' step.")
    if STEP_RESIZE_IMAGES not in kinds:
        raise StepError("Add a 'resize_images' step: every image has to come out the same size, or the rows the model trains on are different lengths.")
    if STEP_FLATTEN_IMAGES not in kinds:
        raise StepError("Add a 'flatten_images' step: a scikit-learn model takes one row of numbers per image, not a grid of pixels.")
    for required, why in ((STEP_TRAIN_MODEL, "train a model"), (STEP_EVALUATE, "evaluate it")):
        if required not in kinds:
            raise StepError(f"Add a '{required}' step: a run has to {why} to produce a result.")
    if kinds.index(STEP_EVALUATE) < kinds.index(STEP_TRAIN_MODEL):
        raise StepError("'evaluate' has to come after 'train_model'.")
    return cleaned

# Steps are stored in the order the learner dropped them on the canvas, but a pipeline
# only works one way round: you cannot scale before you know the target, and a scaler
# fitted before the split has already seen the test rows. Execution and code generation
# both sort through here, so what runs and what is exported can never disagree.
CANONICAL_ORDER = {
    STEP_LOAD_CSV: 0,
    STEP_LAG_FEATURES: 1,
    # Ahead of the cleaning steps because they need to know which column the target is:
    # one-hot encoding a text target would replace it with a set of 0/1 columns.
    STEP_SELECT_TARGET: 2,
    STEP_HANDLE_MISSING: 3,
    STEP_ENCODE_CATEGORICAL: 4,
    STEP_SELECT_FEATURES: 5,
    STEP_TRAIN_TEST_SPLIT: 6,
    STEP_SCALE_FEATURES: 7,
    STEP_TRAIN_MODEL: 8,
    STEP_EVALUATE: 9,
    STEP_PROMPT: 0,
    # The image vocabulary and the tabular one never appear in the same workflow, so these
    # numbers only have to sort correctly against each other.
    STEP_LOAD_IMAGES: 0,
    STEP_RESIZE_IMAGES: 1,
    STEP_GRAYSCALE_IMAGES: 2,
    STEP_FLATTEN_IMAGES: 3,
    STEP_VISION_PROMPT: 0,
}

def ordered_steps(steps):
    """steps is any sequence of objects carrying .kind and .position."""
    return sorted(steps, key=lambda s: (CANONICAL_ORDER.get(s.kind, 99), s.position))
