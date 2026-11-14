"""Renderer interfaces; implementations must remain importable and UI-free."""

from abc import ABC, abstractmethod

from offlook.core.files import FileInfo
from offlook.preview.models import PreviewData, RenderRequest


class Renderer(ABC):
    """No-argument, stateless renderer instantiated inside an isolated worker."""

    @abstractmethod
    def render(self, info: FileInfo, request: RenderRequest) -> PreviewData:
        """Render bounded local content or raise a domain exception on failure."""
        raise NotImplementedError
