"""Reading an image dataset: a ZIP with one folder per class.

The archive is never written to disk. Entries are read out of the ZIP in memory, one at a
time, which is why a hostile entry name cannot escape anywhere: there is no extraction
directory to escape into. Traversal names are still refused outright rather than ignored,
because an archive that contains one is not the archive the uploader meant to build, and
saying so is more use than quietly skipping the file.

Every limit here is checked against the ZIP's declared sizes before a single byte is
decompressed, so a small archive that claims to hold gigabytes is refused rather than
unpacked.
"""
import io
import json
import logging
import zipfile
from app.config import settings

logger = logging.getLogger(__name__)

ALLOWED_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
# Folders macOS and Windows add to a ZIP that the uploader did not ask for. Skipped, not
# refused: telling someone their archive is invalid because Finder wrote a resource fork
# is a message about the tooling, not about their data.
IGNORED_PREFIXES = ("__MACOSX/", ".")
UNLABELLED = ""

# Pillow refuses images above this many pixels rather than allocating for them. Set
# explicitly instead of leaning on the library default, which is a warning by default.
DECODE_PIXEL_LIMIT = 40_000_000

class ImageDatasetError(ValueError):
    """A message written for the uploader. Callers turn it into a 400 or a run error."""

def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000

def _safe_name(raw: str) -> str:
    """Raises unless the entry is a plain relative path. This is the traversal guard."""
    name = raw.replace("\\", "/")
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise ImageDatasetError(f"The archive contains an absolute path ('{raw}'). Zip the class folders themselves, not the path to them.")
    if any(part == ".." for part in name.split("/")):
        raise ImageDatasetError(f"The archive contains a path that points outside itself ('{raw}'). Forge will not read it.")
    return name

def _entries(archive: zipfile.ZipFile) -> list[tuple[str, str, zipfile.ZipInfo]]:
    """Returns (class_name, entry_name, info) for every usable image in the archive."""
    found: list[tuple[str, str, zipfile.ZipInfo]] = []
    declared_total = 0
    per_file_limit = settings.MAX_IMAGE_FILE_MB * 1024 * 1024
    total_limit = settings.MAX_IMAGE_TOTAL_MB * 1024 * 1024
    for info in archive.infolist():
        name = _safe_name(info.filename)
        if _is_symlink(info):
            raise ImageDatasetError(f"The archive contains a link rather than a file ('{info.filename}'). Zip the images themselves.")
        if info.is_dir():
            continue
        parts = [p for p in name.split("/") if p]
        if not parts or any(part.startswith(IGNORED_PREFIXES) for part in parts):
            continue
        if not parts[-1].lower().endswith(ALLOWED_SUFFIXES):
            raise ImageDatasetError(f"'{info.filename}' is not an image Forge can read. Use {', '.join(ALLOWED_SUFFIXES)}.")
        if len(parts) > 2:
            raise ImageDatasetError(f"'{info.filename}' is nested too deep. The archive should be one folder per class, with the images directly inside each folder.")
        if info.file_size > per_file_limit:
            raise ImageDatasetError(f"'{info.filename}' is {info.file_size / 1024 / 1024:.1f} MB and the limit for one image is {settings.MAX_IMAGE_FILE_MB} MB.")
        declared_total += info.file_size
        if declared_total > total_limit:
            raise ImageDatasetError(f"The images unpack to more than {settings.MAX_IMAGE_TOTAL_MB} MB. Shrink them, or upload fewer.")
        if len(found) >= settings.MAX_IMAGE_COUNT:
            raise ImageDatasetError(f"The archive holds more than {settings.MAX_IMAGE_COUNT:,} images, which is the most Forge trains on. Take a sample and upload that.")
        found.append((parts[0] if len(parts) == 2 else UNLABELLED, name, info))
    return found

def open_archive(blob: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise ImageDatasetError("That file could not be read as a ZIP archive. Check it finished uploading, then try again.")

def build_manifest(blob: bytes) -> dict:
    """Validates the archive and returns what is in it. Raises ImageDatasetError."""
    with open_archive(blob) as archive:
        entries = _entries(archive)
        if not entries:
            raise ImageDatasetError(f"No images were found in the archive. Put one folder per class at the top level, each holding {', '.join(ALLOWED_SUFFIXES)} files.")
        counts: dict[str, int] = {}
        images = []
        for class_name, name, info in entries:
            counts[class_name] = counts.get(class_name, 0) + 1
            images.append({"name": name, "class": class_name, "bytes": info.file_size})
        empty = [name for name in archive.namelist() if name.endswith("/") and name.strip("/") and name.strip("/") not in counts and "/" not in name.strip("/")]
        if empty:
            raise ImageDatasetError(f"These class folders have no images in them: {', '.join(sorted(empty)[:10])}. Every class needs at least {settings.MIN_IMAGES_PER_CLASS} images to train on.")
    classes = sorted(c for c in counts if c != UNLABELLED)
    return {"classes": classes, "counts": counts, "images": images, "total": len(images)}

def check_trainable(manifest: dict) -> None:
    """A dataset can be perfectly valid to upload and still not be trainable. Captioning
    works on one loose image; classification needs labelled folders."""
    counts = manifest.get("counts") or {}
    classes = [c for c in counts if c != UNLABELLED]
    if len(classes) < 2:
        raise ImageDatasetError(f"Classification needs at least two classes and this dataset has {len(classes)}. Put the images in one folder per class before zipping them.")
    thin = sorted(c for c in classes if counts[c] < settings.MIN_IMAGES_PER_CLASS)
    if thin:
        raise ImageDatasetError(f"These classes have fewer than {settings.MIN_IMAGES_PER_CLASS} images: {', '.join(thin[:10])}. A model cannot learn a class from a handful of examples, and the score would not mean anything.")

def wrap_single_image(filename: str, data: bytes) -> bytes:
    """A loose image is stored as a one-entry archive, so every image dataset has the same
    shape on the way back out and only one read path exists."""
    safe = filename.replace("\\", "/").rsplit("/", 1)[-1] or "image.png"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(safe, data)
    return buffer.getvalue()

def read_image_bytes(blob: bytes, name: str) -> bytes:
    with open_archive(blob) as archive:
        for _, entry, info in _entries(archive):
            if entry == name:
                return archive.read(info)
    raise ImageDatasetError(f"There is no image called '{name}' in this dataset.")

def decode(data: bytes, *, size: tuple[int, int], grayscale: bool):
    """One image to a flat row of pixel values in 0..1. Exactly what the generated script
    does, so a run and an exported script see the same numbers. Raises ImageDatasetError."""
    import numpy as np
    from PIL import Image, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = DECODE_PIXEL_LIMIT
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("L" if grayscale else "RGB")
            image = image.resize(size)
            return np.asarray(image, dtype=float).reshape(-1) / 255.0
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.warning("Pillow could not decode an image: %s", exc.__class__.__name__)
        raise ImageDatasetError("One of the images could not be decoded. Re-save it as PNG or JPEG and upload again.")

def load_matrix(blob: bytes, *, size: tuple[int, int], grayscale: bool) -> tuple[list, list[str], list[str]]:
    """Returns (rows of pixel values, class label per row, entry name per row)."""
    features: list = []
    labels: list[str] = []
    names: list[str] = []
    with open_archive(blob) as archive:
        for class_name, name, info in _entries(archive):
            features.append(decode(archive.read(info), size=size, grayscale=grayscale))
            labels.append(class_name)
            names.append(name)
    return features, labels, names

def manifest_from_text(text: str) -> dict:
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        raise ImageDatasetError("This dataset's image list could not be read. Upload the archive again.")
    if not isinstance(loaded, dict):
        raise ImageDatasetError("This dataset's image list could not be read. Upload the archive again.")
    return loaded

def shrink_for_vision(data: bytes) -> tuple[bytes, str]:
    """Re-encodes an image down to CAPTION_MAX_EDGE on its longest side and returns
    (bytes, mime). Done before the call, not after: the provider bills an image by how
    many tiles it covers, and a phone photo costs several times what it needs to."""
    from PIL import Image, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = DECODE_PIXEL_LIMIT
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGB")
            edge = settings.CAPTION_MAX_EDGE
            if max(image.size) > edge:
                scale = edge / max(image.size)
                image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.warning("Pillow could not prepare an image for the vision model: %s", exc.__class__.__name__)
        raise ImageDatasetError("That image could not be decoded. Re-save it as PNG or JPEG and upload again.")
    return buffer.getvalue(), "image/jpeg"
