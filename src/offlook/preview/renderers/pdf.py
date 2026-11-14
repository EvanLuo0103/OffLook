"""One-page static PDF rasterization with bounded dimensions and owned handles."""

import math

from offlook.core.errors import FileAccessError, PreviewError
from offlook.core.files import FileInfo
from offlook.preview.models import MAX_RASTER_EDGE, MAX_RASTER_PIXELS, PreviewData, RasterContent, RenderRequest
from offlook.preview.renderers._io import check_unchanged
from offlook.preview.renderers.base import Renderer


class PdfRenderer(Renderer):
    """Reopen one PDF per request without forms, scripts, attachments or links."""

    def render(self, info: FileInfo, request: RenderRequest) -> PreviewData:
        """Return just the requested page; close every native/PIL handle on failure."""
        import pypdfium2 as pdfium

        if info.size_bytes > request.config.max_file_size_bytes:
            raise PreviewError("The PDF exceeds the byte limit; a file information card must be used instead")
        check_unchanged(info)
        document = page = bitmap = image = rgba = None
        try:
            document = pdfium.PdfDocument(info.path, password=None)
            count = len(document)
            if not count:
                raise PreviewError("The PDF is empty and has no pages to preview")
            if not 0 <= request.page_index < count:
                raise PreviewError("The PDF page number is out of range")
            page = document.get_page(request.page_index)
            width, height = page.get_size()
            if not all(math.isfinite(n) and n > 0 for n in (width, height)):
                raise PreviewError("Invalid PDF page dimensions")
            # Render at the requested physical resolution rather than stretching a 2x bitmap.
            scale = min(request.max_width / width, request.max_height / height)
            while True:
                output_width = math.ceil(width * scale)
                output_height = math.ceil(height * scale)
                if (output_width <= min(request.max_width, MAX_RASTER_EDGE)
                        and output_height <= min(request.max_height, MAX_RASTER_EDGE)
                        and output_width * output_height <= MAX_RASTER_PIXELS):
                    break
                scale = math.nextafter(scale, 0.0)
            if not math.isfinite(scale) or scale <= 0:
                raise PreviewError("The PDF page cannot be rendered within safe dimensions")
            bitmap = page.render(scale=scale, may_draw_forms=False, limit_image_cache=True, rev_byteorder=True)
            image = bitmap.to_pil()
            if (image.width > min(request.max_width, MAX_RASTER_EDGE)
                    or image.height > min(request.max_height, MAX_RASTER_EDGE)
                    or image.width * image.height > MAX_RASTER_PIXELS):
                raise PreviewError("The PDF rendering dimensions exceed the requested limit")
            rgba = image.convert("RGBA")
            content = RasterContent(rgba.width, rgba.height, rgba.tobytes())
            check_unchanged(info)
            return PreviewData(info, content, page_index=request.page_index, page_count=count)
        except (PreviewError, FileAccessError):
            raise
        except Exception as exc:
            if getattr(exc, "err_code", None) == 4 or "password" in str(exc).lower():
                raise PreviewError("The PDF requires a password; encrypted previews are not currently supported") from exc
            raise PreviewError(f"PDF parsing failed (the file is damaged or its security scheme is unsupported): {exc}") from exc
        finally:
            for handle in (rgba, image, bitmap, page, document):
                if handle is not None:
                    handle.close()
