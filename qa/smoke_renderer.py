import time

from offlook.preview.models import PreviewData, TextContent
from offlook.preview.renderers.base import Renderer


class BlockingTextRenderer(Renderer):
    def render(self, info, request):
        if request.path.name == 'slow.txt':
            request.path.with_suffix('.started').touch()
            time.sleep(30)
        return PreviewData(info, TextContent(request.path.read_text(encoding='utf-8')))
