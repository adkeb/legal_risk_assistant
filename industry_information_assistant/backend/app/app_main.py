# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

from contextlib import asynccontextmanager
from pathlib import Path
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv
import logging

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from router import research_router
from router.auth_router import router as auth_router
from router.session_router import router as session_router
from router.knowledge_router import router as knowledge_router
from router.attachment_router import router as attachment_router
from core.database import engine, Base
# 导入所有模型以确保它们被注册
from models import (
    User, ChatSession, ChatMessage, ChatAttachment, LongTermMemory,
    KnowledgeBase, Document, ResearchCheckpoint
)

# 创建所有数据表（如果不存在）
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info("应用启动中...")

    logger.info("法律风控专用模式启动：行业资讯、招投标、数据库探索和记忆服务不再启动。")

    yield

    # 关闭时执行
    logger.info("应用关闭中...")
    # 法律风控专用模式不启动行业资讯调度器，无需额外关闭。


app = FastAPI(
    title="法律风控 DeepResearch API",
    description="面向法律风控分析的 AI DeepResearch 系统",
    version="2.0.0",
    lifespan=lifespan
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有源，生产环境中应该设置具体的源
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有方法
    allow_headers=["*"],  # 允许所有头
)

# 注册路由
api_routers = [
    auth_router,
    session_router,
    knowledge_router,
    attachment_router,
    research_router,
]

for router in api_routers:
    app.include_router(router)

for router in api_routers:
    app.include_router(router, prefix="/api")

@app.get("/hello")
@app.get("/api/hello")
async def hello_world():
    """
    Simple hello world endpoint for network verification
    """
    return {
        "status": "success",
        "message": "Hello World! The API is working correctly."
    }


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
FRONTEND_DIST_DIR = Path(os.getenv("FRONTEND_DIST_DIR", str(DEFAULT_FRONTEND_DIST)))
SERVE_FRONTEND = os.getenv("SERVE_FRONTEND", "true").lower() not in {"0", "false", "no"}
API_ROOT_PREFIXES = {
    "api",
    "auth",
    "sessions",
    "knowledge-bases",
    "attachments",
    "research",
    "hello",
}


@app.get("/{full_path:path}", include_in_schema=False)
@app.head("/{full_path:path}", include_in_schema=False)
async def serve_frontend(full_path: str):
    """
    Serve the Vite production build from the backend process when frontend/dist exists.
    API routes are registered before this catch-all and are kept out of the SPA fallback.
    """
    if not SERVE_FRONTEND:
        raise HTTPException(status_code=404, detail="Not Found")

    first_segment = full_path.split("/", 1)[0]
    if first_segment in API_ROOT_PREFIXES:
        raise HTTPException(status_code=404, detail="Not Found")

    if not FRONTEND_DIST_DIR.exists():
        raise HTTPException(status_code=404, detail="Frontend dist not found")

    target = (FRONTEND_DIST_DIR / full_path).resolve()
    try:
        target.relative_to(FRONTEND_DIST_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="Not Found")

    if target.is_file():
        return FileResponse(target)

    index_file = FRONTEND_DIST_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)

    raise HTTPException(status_code=404, detail="Frontend index not found")

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
