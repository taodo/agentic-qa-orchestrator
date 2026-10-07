"""Bound explicit Campaign content/design JSON before parsing, including streams."""
import re
from .errors import error_response

MAX_SOURCE_BODY_BYTES = 524288
SOURCE_PATH = re.compile(r"^/api/v1/projects/[^/]+/campaigns/[^/]+/(?:sources|test-imports|generate-tests)$")


class SourceBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or not SOURCE_PATH.fullmatch(scope["path"]):
            return await self.app(scope, receive, send)
        lengths = [value for key, value in scope["headers"] if key.lower() == b"content-length"]
        if lengths and (len(lengths) != 1 or len(lengths[0]) > 10 or not lengths[0].isdigit() or int(lengths[0]) > MAX_SOURCE_BODY_BYTES):
            return await error_response(413, "SOURCE_SIZE_LIMIT", "Source exceeds supported size")(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect": return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > MAX_SOURCE_BODY_BYTES:
                return await error_response(413, "SOURCE_SIZE_LIMIT", "Source exceeds supported size")(scope, receive, send)
            if chunk:
                chunks.append(chunk)
            if not message.get("more_body", False): break
        replayed = False
        async def bounded_receive():
            nonlocal replayed
            if replayed: return await receive()
            replayed = True
            return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
        return await self.app(scope, bounded_receive, send)
