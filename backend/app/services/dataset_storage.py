"""Storage abstraction for dataset CSV payloads.

Two backends live behind one interface:

* authenticated datasets keep writing to ``data/uploads`` exactly as before,
  so nothing about the existing app changes;
* demo datasets are stored as rows in PostgreSQL. App Runner's filesystem is
  ephemeral, so a demo that wrote to disk would break on the first restart:
  the dataset row survives while the file does not, leaving a dangling
  ``file_path``. Keeping demo bytes in the database also means a sandbox is
  erased atomically with its session.

It also owns the untrusted-input handling for uploads: filename
sanitisation, size ceiling, and CSV structure validation.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.dataset import Dataset
from app.models.demo_dataset_file import DemoDatasetFile

# Bytes read while checking that an upload really is text/CSV.
_SNIFF_BYTES = 64 * 1024
_MAX_COLUMNS = 200
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class InvalidUpload(Exception):
    """The uploaded payload is not a CSV we are willing to store."""


class DatasetPayloadMissing(FileNotFoundError):
    """The dataset exists but its file does not.

    A subclass of FileNotFoundError so existing handlers keep working, with a
    message that names the actual cause instead of looking like a bug.
    """


def safe_filename(raw: str | None, fallback: str = "upload.csv") -> str:
    """Reduce a client supplied filename to a harmless leaf name.

    The original code did ``dataset_dir / file.filename`` with the raw value,
    which lets ``../../app/main.py`` escape the upload directory and overwrite
    application code. Everything path-like is stripped here: the result can
    never contain a separator, a drive letter, or a parent reference.
    """
    if not raw:
        return fallback
    # Take the last segment under both POSIX and Windows separators, then drop
    # anything that is not a plain name character.
    leaf = re.split(r"[\\/]", raw)[-1]
    leaf = _SAFE_NAME.sub("_", leaf).strip("._-")
    if not leaf:
        return fallback
    if not leaf.lower().endswith(".csv"):
        leaf = f"{leaf}.csv"
    return leaf[:120]


def validate_csv_bytes(content: bytes) -> list[str]:
    """Confirm the payload decodes as text and parses as a CSV with a header.

    Returns the header row. Raises :class:`InvalidUpload` otherwise. An
    ``accept=".csv"`` attribute in the browser is cosmetic, so the extension
    is never trusted; only the actual bytes are.
    """
    if not content:
        raise InvalidUpload("El archivo esta vacio.")
    if b"\x00" in content[:_SNIFF_BYTES]:
        raise InvalidUpload("El archivo no es un CSV de texto plano.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1")
        except Exception as exc:  # pragma: no cover - latin-1 accepts any byte
            raise InvalidUpload("No se pudo decodificar el archivo como texto.") from exc

    try:
        reader = csv.reader(io.StringIO(text))
        header = next(reader, None)
    except csv.Error as exc:
        raise InvalidUpload(f"El CSV no se pudo interpretar: {exc}") from exc

    if not header:
        raise InvalidUpload("El CSV no tiene encabezado.")
    if len(header) > _MAX_COLUMNS:
        raise InvalidUpload(f"El CSV supera las {_MAX_COLUMNS} columnas permitidas.")
    if all(not (col or "").strip() for col in header):
        raise InvalidUpload("El encabezado del CSV esta vacio.")

    try:
        first_row = next(reader, None)
    except csv.Error as exc:
        raise InvalidUpload(f"El CSV no se pudo interpretar: {exc}") from exc
    if first_row is None:
        raise InvalidUpload("El CSV no contiene filas de datos.")

    return [(col or "").strip() for col in header]


# --- demo backend ----------------------------------------------------------


def store_demo_file(
    db: Session,
    dataset: Dataset,
    filename: str,
    content: bytes,
) -> DemoDatasetFile:
    """Persist (or replace) the CSV that backs a demo dataset."""
    existing = (
        db.query(DemoDatasetFile).filter(DemoDatasetFile.dataset_id == dataset.id).first()
    )
    if existing is not None:
        existing.filename = filename
        existing.size_bytes = len(content)
        existing.content = content
        record = existing
    else:
        record = DemoDatasetFile(
            demo_session_id=dataset.demo_session_id,
            dataset_id=dataset.id,
            filename=filename,
            size_bytes=len(content),
            content=content,
        )
        db.add(record)
    # ``file_path`` stays a display label for demo datasets; it is never
    # resolved against the filesystem.
    dataset.file_path = f"demo://{dataset.demo_session_id}/{filename}"
    db.commit()
    db.refresh(record)
    return record


def demo_file_size(db: Session, dataset_id: int) -> int:
    row = (
        db.query(DemoDatasetFile.size_bytes)
        .filter(DemoDatasetFile.dataset_id == dataset_id)
        .first()
    )
    return int(row[0]) if row else 0


def read_demo_bytes(db: Session, dataset: Dataset) -> bytes | None:
    row = db.query(DemoDatasetFile).filter(DemoDatasetFile.dataset_id == dataset.id).first()
    return bytes(row.content) if row else None


# --- unified reads ---------------------------------------------------------


def open_dataset_text(db: Session, dataset: Dataset) -> io.StringIO | Any:
    """Return a text handle over the dataset payload, whatever the backend."""
    if dataset.demo_session_id:
        raw = read_demo_bytes(db, dataset)
        if raw is None:
            raise FileNotFoundError("Demo dataset file not found")
        try:
            return io.StringIO(raw.decode("utf-8-sig"))
        except UnicodeDecodeError:
            return io.StringIO(raw.decode("latin-1"))

    if not dataset.file_path:
        raise FileNotFoundError("Dataset has no file")
    path = Path(dataset.file_path)
    if not path.exists():
        # The dataset row survived and its file did not. On a container with
        # ephemeral storage that is what a restart or a redeploy looks like,
        # and reporting it as a plain "not found" made it read like a bug in
        # the application. Say what happened and what to do about it.
        raise DatasetPayloadMissing(
            "El archivo de este dataset ya no esta disponible en esta instancia. "
            "El almacenamiento local no sobrevive a reinicios ni a un cambio de "
            "instancia: volve a subir el CSV o genera los datos otra vez."
        )
    return path.open("r", encoding="utf-8", errors="replace", newline="")


def load_dataset_records(db: Session, dataset: Dataset) -> list[dict[str, Any]]:
    """Parse the dataset into records, from disk or from the database."""
    handle = open_dataset_text(db, dataset)
    try:
        return [row for row in csv.DictReader(handle)]
    finally:
        close = getattr(handle, "close", None)
        if callable(close):
            close()


def dataset_has_payload(db: Session, dataset: Dataset) -> bool:
    if dataset.demo_session_id:
        return (
            db.query(DemoDatasetFile.id)
            .filter(DemoDatasetFile.dataset_id == dataset.id)
            .first()
            is not None
        )
    return bool(dataset.file_path) and Path(dataset.file_path).exists()
