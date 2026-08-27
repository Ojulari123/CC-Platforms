import io
import json
import zipfile
import pytest
from PIL import Image
from app.models import Dataset, LlmUsage, Workflow, WorkflowRun, WorkflowStep
from app.services import codegen, datasets as dataset_service, images, runs as run_service
from app.services.ai_provider import AIError, AIResult
from app.services.steps import StepError, validate_sequence

CLASSES = ("dark", "light")

def _png(shade: int, side: int = 24) -> bytes:
    image = Image.new("RGB", (side, side), (shade, shade, shade))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()

def _archive(entries) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()

def _dataset_archive(per_class: int = 8) -> bytes:
    entries = []
    for index in range(per_class):
        entries.append((f"dark/dark_{index}.png", _png(20 + index)))
        entries.append((f"light/light_{index}.png", _png(220 + index)))
    return _archive(entries)

def _image_dataset(db, owner=1, blob=None) -> Dataset:
    return dataset_service.create_image_dataset(db, owner, "Shades", "shades.zip", blob or _dataset_archive())

def _image_steps():
    return [
        ("load_images", {}),
        ("resize_images", {"width": 16, "height": 16}),
        ("grayscale_images", {}),
        ("flatten_images", {}),
        ("scale_features", {"strategy": "standard"}),
        ("train_test_split", {"test_size": 0.25, "random_state": 42, "shuffle": True}),
        ("train_model", {"algorithm": "logistic_regression", "hyperparameters": {"max_iter": 200}}),
        ("evaluate", {}),
    ]

def _workflow(db, dataset, kind="image_classification", steps=None, owner=1) -> Workflow:
    workflow = Workflow(owner_user_id=owner, name="Shade sorter", kind=kind, dataset_id=dataset.id)
    workflow.steps = [
        WorkflowStep(position=index, kind=step_kind, params=json.dumps(params))
        for index, (step_kind, params) in enumerate(steps or _image_steps())
    ]
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow

def _run_row(db, workflow, owner=1) -> WorkflowRun:
    run = WorkflowRun(workflow_id=workflow.id, owner_user_id=owner, status="queued")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run

# --- the archive, and the things people upload that are not one -------------------------

def test_a_class_folder_archive_becomes_an_image_dataset(db):
    dataset = _image_dataset(db)
    assert (dataset.kind, dataset.row_count) == ("image", 16)
    assert json.loads(dataset.columns) == list(CLASSES)
    assert json.loads(dataset.content)["counts"] == {"dark": 8, "light": 8}

def test_a_path_traversal_entry_is_refused_and_nothing_is_written(db, tmp_path):
    escape = tmp_path / "escaped.png"
    blob = _archive([("dark/a.png", _png(20)), ("../../../../../../../../" + str(escape).lstrip("/"), _png(20))])
    with pytest.raises(Exception) as caught:
        dataset_service.create_image_dataset(db, 1, "Hostile", "hostile.zip", blob)
    assert "points outside itself" in str(caught.value.detail)
    assert not escape.exists()
    assert db.query(Dataset).count() == 0

def test_an_absolute_path_entry_is_refused(db):
    blob = _archive([("/etc/passwd.png", _png(20))])
    with pytest.raises(Exception) as caught:
        dataset_service.create_image_dataset(db, 1, "Hostile", "hostile.zip", blob)
    assert "absolute path" in str(caught.value.detail)

def test_a_file_that_is_not_a_zip_is_refused(db):
    with pytest.raises(Exception) as caught:
        dataset_service.create_image_dataset(db, 1, "Broken", "broken.zip", b"PK\x03\x04 not really a zip at all")
    assert "could not be read as a ZIP" in str(caught.value.detail)

def test_an_archive_of_the_wrong_file_type_is_refused(db):
    with pytest.raises(Exception) as caught:
        dataset_service.create_image_dataset(db, 1, "Notes", "notes.zip", _archive([("dark/notes.txt", b"hello")]))
    assert "not an image Forge can read" in str(caught.value.detail)

def test_images_nested_deeper_than_one_folder_are_refused(db):
    with pytest.raises(Exception) as caught:
        dataset_service.create_image_dataset(db, 1, "Deep", "deep.zip", _archive([("a/b/c.png", _png(20))]))
    assert "nested too deep" in str(caught.value.detail)

def test_an_empty_class_folder_is_named_in_the_error(db):
    blob = _archive([("dark/", b""), ("light/a.png", _png(220)), ("empty/", b"")])
    with pytest.raises(Exception) as caught:
        dataset_service.create_image_dataset(db, 1, "Gappy", "gappy.zip", blob)
    assert "empty/" in str(caught.value.detail) and "no images" in str(caught.value.detail)

def test_an_oversized_image_is_refused_before_it_is_decompressed(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.MAX_IMAGE_FILE_MB", 0)
    with pytest.raises(Exception) as caught:
        dataset_service.create_image_dataset(db, 1, "Big", "big.zip", _dataset_archive())
    assert "the limit for one image" in str(caught.value.detail)

def test_a_symlink_entry_is_refused(db):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("dark/link.png")
        info.external_attr = (0o120777 << 16)
        archive.writestr(info, "/etc/passwd")
    with pytest.raises(Exception) as caught:
        dataset_service.create_image_dataset(db, 1, "Link", "link.zip", buffer.getvalue())
    assert "a link rather than a file" in str(caught.value.detail)

def test_a_single_image_is_stored_as_a_one_entry_archive(db):
    dataset = dataset_service.create_image_dataset(db, 1, "One", "cat.png", _png(90))
    assert (dataset.kind, dataset.row_count) == ("image", 1)
    assert json.loads(dataset.content)["images"][0]["name"] == "cat.png"
    # No class folder, so there is nothing to classify. It is still fine to ask about.
    with pytest.raises(images.ImageDatasetError):
        images.check_trainable(json.loads(dataset.content))

def test_one_class_is_not_enough_to_classify(db):
    dataset = _image_dataset(db, blob=_archive([(f"dark/{i}.png", _png(20 + i)) for i in range(8)]))
    run = run_service.execute_run(db, _run_row(db, _workflow(db, dataset)).id)
    assert run.status == "failed"
    assert "at least two classes" in run.error

def test_a_class_with_too_few_images_is_named(db):
    blob = _archive([("dark/a.png", _png(20)), ("dark/b.png", _png(24))] + [(f"light/{i}.png", _png(220)) for i in range(6)])
    dataset = _image_dataset(db, blob=blob)
    run = run_service.execute_run(db, _run_row(db, _workflow(db, dataset)).id)
    assert run.status == "failed"
    assert "fewer than 5 images" in run.error and "dark" in run.error

# --- the steps --------------------------------------------------------------------------

def test_an_image_workflow_without_flatten_is_refused():
    steps = [(kind, params) for kind, params in _image_steps() if kind != "flatten_images"]
    with pytest.raises(StepError) as caught:
        validate_sequence("image_classification", steps)
    assert "flatten_images" in str(caught.value)

def test_an_image_workflow_without_resize_is_refused():
    steps = [(kind, params) for kind, params in _image_steps() if kind != "resize_images"]
    with pytest.raises(StepError) as caught:
        validate_sequence("image_classification", steps)
    assert "the same size" in str(caught.value)

def test_a_resize_bigger_than_the_ceiling_is_refused():
    steps = [(kind, {"width": 256, "height": 256} if kind == "resize_images" else params) for kind, params in _image_steps()]
    with pytest.raises(StepError) as caught:
        validate_sequence("image_classification", steps)
    assert "between 8 and 64 pixels" in str(caught.value)

def test_a_tabular_step_has_no_place_in_an_image_workflow():
    with pytest.raises(StepError) as caught:
        validate_sequence("image_classification", _image_steps() + [("encode_categorical", {})])
    assert "has no 'encode_categorical' step" in str(caught.value)

def test_a_vision_workflow_is_exactly_one_step():
    with pytest.raises(StepError) as caught:
        validate_sequence("llm_vision", [("vision_prompt", {"image": "a.png"}), ("vision_prompt", {"image": "b.png"})])
    assert "exactly one 'vision_prompt' step" in str(caught.value)

def test_a_vision_step_defaults_to_asking_for_a_caption():
    cleaned = validate_sequence("llm_vision", [("vision_prompt", {"image": "a.png"})])[0]
    assert cleaned["prompt"].startswith("Describe this image")

# --- training ---------------------------------------------------------------------------

def test_an_image_run_trains_and_reports_a_confusion_matrix_with_class_names(db):
    workflow = _workflow(db, _image_dataset(db))
    run = run_service.execute_run(db, _run_row(db, workflow).id)
    assert run.status == "succeeded", run.error
    metrics, result = json.loads(run.metrics), json.loads(run.result)
    assert set(metrics) == {"accuracy", "precision_macro", "recall_macro", "f1_macro"}
    assert result["class_labels"] == list(CLASSES)
    assert len(result["confusion_matrix"]) == 2
    assert result["features_per_image"] == 16 * 16  # grayscale, so one channel
    assert result["images_used"] == 16
    assert result["predictions_sample"][0]["image"] in {entry["name"] for entry in json.loads(workflow_dataset(db).content)["images"]}

def workflow_dataset(db) -> Dataset:
    return db.query(Dataset).one()

def test_colour_costs_three_times_the_features(db):
    steps = [(kind, params) for kind, params in _image_steps() if kind != "grayscale_images"]
    run = run_service.execute_run(db, _run_row(db, _workflow(db, _image_dataset(db), steps=steps)).id)
    assert run.status == "succeeded", run.error
    assert json.loads(run.result)["features_per_image"] == 16 * 16 * 3

def test_the_weakness_of_flattened_pixels_is_written_on_the_result(db):
    run = run_service.execute_run(db, _run_row(db, _workflow(db, _image_dataset(db))).id)
    note = json.loads(run.result)["method_note"]
    assert "convolutional" in note and "throws away where each pixel was" in note

def test_too_many_numbers_is_refused_with_a_way_out(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.MAX_TRAIN_CELLS", 100)
    run = run_service.execute_run(db, _run_row(db, _workflow(db, _image_dataset(db))).id)
    assert run.status == "failed"
    assert "Resize smaller" in run.error

def test_a_deleted_image_dataset_fails_the_run_with_a_sentence(db):
    workflow = _workflow(db, _image_dataset(db))
    db.delete(db.query(Dataset).one())
    db.commit()
    run = run_service.execute_run(db, _run_row(db, workflow).id)
    assert run.status == "failed"
    assert run.error == "The image dataset this workflow used has been deleted, so there is nothing to train on."

# --- asking a question about an image ---------------------------------------------------

def test_a_vision_run_stores_the_reply_and_meters_it_as_vision(db, monkeypatch):
    seen = {}

    def _describe(system, user, image_bytes, *, mime, max_tokens):
        seen["system"], seen["user"], seen["mime"], seen["bytes"] = system, user, mime, len(image_bytes)
        return AIResult(text="A dark grey square.", model="gpt-4o-mini", token_count=8_400)

    monkeypatch.setattr("app.services.runs.describe_image", _describe)
    dataset = dataset_service.create_image_dataset(db, 1, "One", "cat.png", _png(90))
    workflow = _workflow(db, dataset, kind="llm_vision", steps=[("vision_prompt", {"image": "cat.png", "prompt": "What colour is it?", "max_tokens": 100})])
    run = run_service.execute_run(db, _run_row(db, workflow).id)
    assert run.status == "succeeded", run.error
    result = json.loads(run.result)
    assert result["reply"] == "A dark grey square."
    assert (result["image"], result["sent_max_edge"]) == ("cat.png", 512)
    assert seen["user"] == "What colour is it?" and seen["mime"] == "image/jpeg"
    usage = db.query(LlmUsage).one()
    assert (usage.kind, usage.tokens, usage.run_id) == ("vision", 8_400, run.id)

def test_the_image_is_shrunk_before_it_is_sent(db, monkeypatch):
    sent = {}

    def _describe(system, user, image_bytes, *, mime, max_tokens):
        sent["bytes"] = image_bytes
        return AIResult(text="ok", model="gpt-4o-mini", token_count=10)

    monkeypatch.setattr("app.services.runs.describe_image", _describe)
    dataset = dataset_service.create_image_dataset(db, 1, "Wide", "wide.png", _png(90, side=1600))
    workflow = _workflow(db, dataset, kind="llm_vision", steps=[("vision_prompt", {"image": "wide.png", "prompt": "What is it?", "max_tokens": 50})])
    assert run_service.execute_run(db, _run_row(db, workflow).id).status == "succeeded"
    with Image.open(io.BytesIO(sent["bytes"])) as shrunk:
        assert max(shrunk.size) == 512

def test_a_vision_run_that_names_a_missing_image_fails_with_a_sentence(db, monkeypatch):
    monkeypatch.setattr("app.services.runs.describe_image", lambda *a, **k: AIResult(text="x", model="m", token_count=1))
    dataset = dataset_service.create_image_dataset(db, 1, "One", "cat.png", _png(90))
    workflow = _workflow(db, dataset, kind="llm_vision", steps=[("vision_prompt", {"image": "dog.png", "prompt": "What is it?", "max_tokens": 50})])
    run = run_service.execute_run(db, _run_row(db, workflow).id)
    assert run.status == "failed"
    assert "no image called 'dog.png'" in run.error
    assert db.query(LlmUsage).count() == 0

def test_a_provider_failure_on_a_vision_run_costs_nothing(db, monkeypatch):
    def _boom(system, user, image_bytes, *, mime, max_tokens):
        raise AIError("The language model could not be reached. Try again shortly.")

    monkeypatch.setattr("app.services.runs.describe_image", _boom)
    dataset = dataset_service.create_image_dataset(db, 1, "One", "cat.png", _png(90))
    workflow = _workflow(db, dataset, kind="llm_vision", steps=[("vision_prompt", {"image": "cat.png", "prompt": "What is it?", "max_tokens": 50})])
    run = run_service.execute_run(db, _run_row(db, workflow).id)
    assert run.status == "failed"
    assert db.query(LlmUsage).count() == 0

def test_the_image_cost_is_counted_against_the_cap_before_the_call(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.LLM_DAILY_TOKEN_CAP", 5_000)
    dataset = dataset_service.create_image_dataset(db, 1, "One", "cat.png", _png(90))
    workflow = _workflow(db, dataset, kind="llm_vision", steps=[("vision_prompt", {"image": "cat.png", "prompt": "hi", "max_tokens": 50})])
    with pytest.raises(Exception) as caught:
        run_service.start_run(db, workflow.id, 1)
    assert caught.value.status_code == 429
    assert "daily tokens left" in caught.value.detail

# --- generated code ---------------------------------------------------------------------

def test_the_image_script_names_every_step_and_says_what_flattening_costs(db):
    workflow = _workflow(db, _image_dataset(db))
    code = codegen.generate_script(workflow, workflow.steps, data_path="images")
    for kind in ("load_images", "resize_images", "grayscale_images", "flatten_images", "scale_features", "train_test_split", "train_model", "evaluate"):
        assert f"— {kind}:" in code
    assert "pip install numpy pillow scikit-learn" in code
    assert "convolutional network" in code
    assert "confusion_matrix(y_test, predictions, labels=labels_sorted)" in code
    compile(code, "image.py", "exec")

def test_the_vision_script_reads_the_key_from_the_environment_and_never_holds_it(db):
    dataset = dataset_service.create_image_dataset(db, 1, "One", "cat.png", _png(90))
    workflow = _workflow(db, dataset, kind="llm_vision", steps=[("vision_prompt", {"image": "cat.png", "prompt": "What is it?", "max_tokens": 60})])
    code = codegen.generate_script(workflow, workflow.steps, data_path="images")
    assert 'os.environ["OPENAI_API_KEY"]' in code
    assert "base64.b64encode" in code and "— vision_prompt:" in code
    compile(code, "vision.py", "exec")

def test_the_image_notebook_has_a_cell_per_step(db):
    workflow = _workflow(db, _image_dataset(db))
    notebook = codegen.generate_notebook(workflow, workflow.steps, data_path="images")
    code_cells = [c for c in notebook["cells"] if c["cell_type"] == "code"]
    assert len(code_cells) == len(workflow.steps) + 1  # one per step, plus the imports cell

# --- the API surface --------------------------------------------------------------------

def test_uploading_and_reading_back_an_image_dataset(client, act_as, db):
    act_as(1)
    response = client.post("/datasets/images", files={"file": ("shades.zip", _dataset_archive(), "application/zip")}, data={"name": "Shades"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["kind"], body["row_count"], body["columns"]) == ("image", 16, list(CLASSES))

    manifest = client.get(f"/datasets/{body['id']}/images")
    assert manifest.status_code == 200
    assert manifest.json()["counts"] == {"dark": 8, "light": 8}
    assert "convolutional" in manifest.json()["method_note"]
    assert manifest.json()["images"][0]["class"] == "dark"

def test_an_image_dataset_has_no_csv_preview(client, act_as, db):
    act_as(1)
    dataset = _image_dataset(db)
    response = client.get(f"/datasets/{dataset.id}/preview")
    assert response.status_code == 400
    assert "images endpoint" in response.json()["detail"]

def test_a_csv_dataset_has_no_image_list(client, act_as, db):
    act_as(1)
    dataset = dataset_service.create_dataset(db, 1, "Houses", "h.csv", b"a,b\n1,2\n")
    response = client.get(f"/datasets/{dataset.id}/images")
    assert response.status_code == 400
    assert "preview endpoint" in response.json()["detail"]

def test_an_image_workflow_will_not_take_a_csv(client, act_as, db):
    act_as(1)
    dataset = dataset_service.create_dataset(db, 1, "Houses", "h.csv", b"a,b\n1,2\n")
    response = client.post("/workflows", json={
        "name": "wrong", "kind": "image_classification", "dataset_id": dataset.id,
        "steps": [{"kind": kind, "params": params} for kind, params in _image_steps()],
    })
    assert response.status_code == 400
    assert "holds tabular data" in response.json()["detail"]

def test_an_image_upload_over_the_limit_is_refused(client, act_as, db, monkeypatch):
    act_as(1)
    monkeypatch.setattr("app.config.settings.MAX_IMAGE_UPLOAD_MB", 0)
    response = client.post("/datasets/images", files={"file": ("shades.zip", _dataset_archive(), "application/zip")})
    assert response.status_code == 413
    assert "0 MB limit" in response.json()["detail"]

def test_the_step_catalog_offers_the_image_vocabulary(client, act_as):
    act_as(1)
    body = client.get("/workflows/steps").json()
    assert body["steps_by_workflow_kind"]["image_classification"] == [
        "load_images", "resize_images", "grayscale_images", "flatten_images",
        "scale_features", "train_test_split", "train_model", "evaluate",
    ]
    assert body["steps_by_workflow_kind"]["llm_vision"] == ["vision_prompt"]
    flatten = next(step for step in body["steps"] if step["kind"] == "flatten_images")
    assert "position is lost" in flatten["summary"]
