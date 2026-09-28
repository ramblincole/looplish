from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from starlette.exceptions import HTTPException

RESERVED_PREFIXES = ("api/", "health/")
RESERVED_EXACT = {"api", "health"}


def mount_static_site(app: FastAPI, dist: Path) -> None:
    root = dist.resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError("LOOPLISH_WEB_DIST_DIR does not contain index.html")

    @app.get("/{path:path}", include_in_schema=False)
    async def static(path: str, request: Request) -> Response:
        # API/健康检查永远保留自己的 404（Problem Details），不能被 SPA 的 index.html 掩盖。
        if path in RESERVED_EXACT or path.startswith(RESERVED_PREFIXES):
            raise HTTPException(status_code=404)
        candidate = (root / path).resolve()
        # resolve 后验证父目录，阻止 ../ 或符号链接逃出 dist。
        if candidate != root and root not in candidate.parents:
            raise HTTPException(status_code=404)
        if candidate.is_file():
            cache = (
                "public, max-age=31536000, immutable" if "/assets/" in f"/{path}" else "no-cache"
            )
            return FileResponse(candidate, headers={"Cache-Control": cache})
        # 只有声明接受 HTML 的页面导航才使用 SPA fallback；缺失的脚本、图片仍是 404。
        if "text/html" in request.headers.get("accept", ""):
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        raise HTTPException(status_code=404)
