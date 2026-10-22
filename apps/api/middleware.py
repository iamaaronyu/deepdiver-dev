"""Bound request bodies before JSON parsing, including chunked uploads."""
from fastapi.responses import JSONResponse


class RequestBodyLimit:
    def __init__(self, app, max_bytes=32768):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        chunks = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                response = JSONResponse(status_code=413, content={
                    "request_id": scope.get("state", {}).get("request_id", ""),
                    "error": {"code": "request_too_large", "message": "请求体不能超过 32 KiB。"},
                })
                return await response(scope, receive, send)
            chunks.append(message)
            if not message.get("more_body", False):
                break
        iterator = iter(chunks)

        async def replay():
            message = next(iterator, None)
            return message if message is not None else await receive()

        await self.app(scope, replay, send)
