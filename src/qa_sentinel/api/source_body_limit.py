"""Bound explicit Campaign content/design JSON before parsing, including streams."""
import re
from .errors import error_response

MAX_SOURCE_BODY_BYTES = 524288
MAX_REVIEW_BODY_BYTES = 8192
REVIEW_PATH = re.compile(r"^/api/v1/projects/[^/]+/campaigns/[^/]+/(?:requirements|test-specifications)/[^/]+/review$")
RUN_PATH = re.compile(r"^/api/v1/projects/[^/]+/campaigns/[^/]+/runs$")
SOURCE_PATH = re.compile(r"^/api/v1/projects/[^/]+/campaigns/[^/]+/(?:sources|test-imports|generate-tests)$")


class SourceBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        review = REVIEW_PATH.fullmatch(scope["path"])
        run = RUN_PATH.fullmatch(scope["path"])
        if not review and not run and not SOURCE_PATH.fullmatch(scope["path"]):
            return await self.app(scope, receive, send)
        maximum = MAX_REVIEW_BODY_BYTES if review or run else MAX_SOURCE_BODY_BYTES
        code = "RUN_REQUEST_SIZE_LIMIT" if run else "REVIEW_SIZE_LIMIT" if review else "SOURCE_SIZE_LIMIT"
        error_message = "Run request exceeds supported size" if run else "Review request exceeds supported size" if review else "Source exceeds supported size"
        lengths = [value for key, value in scope["headers"] if key.lower() == b"content-length"]
        if lengths and (len(lengths) != 1 or len(lengths[0]) > 10 or not lengths[0].isdigit() or int(lengths[0]) > maximum):
            return await error_response(413, code, error_message)(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect": return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > maximum:
                return await error_response(413, code, error_message)(scope, receive, send)
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
