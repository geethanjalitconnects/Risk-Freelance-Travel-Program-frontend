"""Private file storage for encrypted documents. It has no URL: files are only ever read by
the admin document view, which checks permissions, decrypts and logs the access."""
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage


class PrivateStorage(FileSystemStorage):
    def url(self, name):
        raise NotImplementedError("Private documents have no public URL.")


def get_storage() -> PrivateStorage:
    # Built per call so tests (and deployments) can change PRIVATE_MEDIA_ROOT.
    return PrivateStorage(location=str(settings.PRIVATE_MEDIA_ROOT), base_url=None)


def save_encrypted(data: bytes) -> str:
    """Store already-encrypted bytes under a random name (no user id or document type in it)."""
    return get_storage().save(f"verification/{uuid.uuid4().hex}.bin", ContentFile(data))


def read(name: str) -> bytes:
    with get_storage().open(name, "rb") as f:
        return f.read()


def delete(name: str) -> None:
    if name:
        get_storage().delete(name)
