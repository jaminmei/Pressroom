from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app
from app.storage.local import get_storage

pytestmark = pytest.mark.usefixtures(
    "authenticated_workspace_contract",
    "file_resource_database",
)


@pytest.fixture
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    get_storage.cache_clear()
    yield tmp_path
    get_storage.cache_clear()
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_upload_pdf_success(isolated_storage: Path) -> None:
    payload = b"%PDF-1.4\nmock-pdf"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/files/upload",
            files={"file": ("document.pdf", payload, "application/pdf")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["file_id"].startswith("file_")
    assert body["filename"] == "document.pdf"
    assert body["mime_type"] == "application/pdf"
    assert body["size_bytes"] == len(payload)

    # storage_path is no longer exposed in API response (security fix);
    # verify file was saved via the internal file store instead.
    from app.api.files import get_file_store

    record = get_file_store().get(body["file_id"])
    assert record is not None
    saved_path = isolated_storage / record.storage_path
    assert saved_path.exists()
    assert saved_path.read_bytes() == payload


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mime_type", "filename"),
    [
        ("image/png", "image.png"),
        ("image/jpeg", "image.jpg"),
        ("image/webp", "image.webp"),
        ("image/bmp", "image.bmp"),
        ("image/tiff", "image.tiff"),
    ],
)
async def test_upload_image_success(isolated_storage: Path, mime_type: str, filename: str) -> None:
    payload = b"fake-image-content"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/files/upload",
            files={"file": (filename, payload, mime_type)},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == filename
    assert body["mime_type"] == mime_type
    assert body["size_bytes"] == len(payload)


@pytest.mark.anyio
async def test_upload_image_jpg_alias_success(isolated_storage: Path) -> None:
    payload = b"fake-image-content"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/files/upload",
            files={"file": ("alias.jpg", payload, "image/jpg")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["mime_type"] == "image/jpg"
    assert body["filename"] == "alias.jpg"
    assert body["size_bytes"] == len(payload)


@pytest.mark.anyio
async def test_upload_unsupported_type(isolated_storage: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/files/upload",
            files={"file": ("archive.zip", b"PK\x03\x04", "application/zip")},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "UNSUPPORTED_FILE_TYPE"


@pytest.mark.anyio
async def test_upload_rejects_empty_content_type(isolated_storage: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/files/upload",
            files={"file": ("unknown.bin", b"content", "")},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "UNSUPPORTED_FILE_TYPE"


@pytest.mark.anyio
async def test_upload_rejects_none_content_type(isolated_storage: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/files/upload",
            files={"file": ("unknown.bin", b"content", None)},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "UNSUPPORTED_FILE_TYPE"


@pytest.mark.anyio
async def test_upload_too_large(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep payload tiny and force a zero-byte limit to avoid multipart parser hard limits.
    monkeypatch.setenv("MAX_FILE_SIZE_MB", "0")
    get_settings.cache_clear()
    oversized_payload = b"x"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/files/upload",
            files={"file": ("large.pdf", oversized_payload, "application/pdf")},
        )

    assert response.status_code == 413
    body = response.json()
    assert body["error_code"] == "FILE_TOO_LARGE"


@pytest.mark.anyio
async def test_upload_size_equal_limit_is_allowed(
    isolated_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_FILE_SIZE_MB", "1")
    get_settings.cache_clear()
    payload = b"x" * (1024 * 1024)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/files/upload",
            files={"file": ("limit.pdf", payload, "application/pdf")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "limit.pdf"
    assert body["size_bytes"] == len(payload)


@pytest.mark.anyio
async def test_upload_empty_file(isolated_storage: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/files/upload",
            files={"file": ("empty.txt", b"", "text/plain")},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "EMPTY_FILE"


@pytest.mark.anyio
async def test_upload_html_success(isolated_storage: Path) -> None:
    payload = b"<html><body><h1>Hello</h1></body></html>"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/files/upload",
            files={"file": ("page.html", payload, "text/html")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "page.html"
    assert body["mime_type"] == "text/html"
    assert body["size_bytes"] == len(payload)


@pytest.mark.anyio
async def test_upload_sanitizes_unix_path_traversal_filename(isolated_storage: Path) -> None:
    payload = b"%PDF-1.4\nmock-pdf"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/files/upload",
            files={"file": ("../../a.pdf", payload, "application/pdf")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "a.pdf"
    # storage_path no longer in response; verify sanitized name via file store
    from app.api.files import get_file_store

    record = get_file_store().get(body["file_id"])
    assert (isolated_storage / record.storage_path).name == "a.pdf"


@pytest.mark.anyio
async def test_upload_sanitizes_windows_path_traversal_filename(isolated_storage: Path) -> None:
    payload = b"%PDF-1.4\nmock-pdf"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/files/upload",
            files={"file": ("..\\..\\a.pdf", payload, "application/pdf")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "a.pdf"
    from app.api.files import get_file_store

    record = get_file_store().get(body["file_id"])
    assert (isolated_storage / record.storage_path).name == "a.pdf"
