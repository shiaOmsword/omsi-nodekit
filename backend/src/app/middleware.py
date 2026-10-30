
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
@app.middleware("http")
    async def local_requests_only(request: Request, call_next):
        if request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            return JSONResponse(
                {"detail": "Nodekit accepts localhost requests only"}, status_code=403
            )
        if request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and origin not in {
                "http://127.0.0.1:8765",
                "http://localhost:8765",
                "http://127.0.0.1:5173",
                "http://localhost:5173",
            }:
                return JSONResponse({"detail": "Untrusted browser origin"}, status_code=403)
            if (
                request.method not in {"GET", "HEAD"}
                and request.headers.get("x-nodekit-request") != "1"
            ):
                return JSONResponse({"detail": "Missing X-Nodekit-Request header"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response