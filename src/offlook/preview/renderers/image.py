"""First-frame image decoding with conservative pixel and output limits."""

import warnings

from offlook.core.errors import PreviewError
from offlook.core.files import FileInfo
from offlook.preview.models import PreviewData, RasterContent, RenderRequest
from offlook.preview.renderers._io import open_checked
from offlook.preview.renderers.base import Renderer


class ImageRenderer(Renderer):
    """Decode an approved raster format without external viewers or animation."""

    def render(self, info: FileInfo, request: RenderRequest) -> PreviewData:
        """Return bounded oriented RGBA pixels; raise PreviewError on bad images."""
        from PIL import Image, ImageOps

        if info.size_bytes > request.config.max_file_size_bytes:
            raise PreviewError("The image exceeds the byte limit; a file information card must be used instead")
        Image.MAX_IMAGE_PIXELS = 25000000
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with open_checked(info) as stream:
                    with Image.open(stream, formats=("JPEG", "PNG", "GIF", "BMP", "TIFF", "WEBP", "ICO")) as image:
                        if max(image.size) > 32768 or image.width * image.height > 25000000:
                            raise PreviewError("The image pixel count or edge length exceeds the safety limit")
                        image.seek(0)
                        orientation = image.getexif().get(274, 1)
                        target = (request.max_width, request.max_height)
                        if orientation in (5, 6, 7, 8):
                            target = (target[1], target[0])
                        image.thumbnail(target, Image.Resampling.LANCZOS, reducing_gap=2.0)
                        ImageOps.exif_transpose(image, in_place=True)
                        with image.convert("RGBA") as rgba:
                            content = RasterContent(rgba.width, rgba.height, rgba.tobytes())
            return PreviewData(info, content, "Showing only the first image frame")
        except PreviewError:
            raise
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
            raise PreviewError(f"Image decoding failed: {exc}") from exc
