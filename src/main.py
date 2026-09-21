import sys
from pathlib import Path

# 将项目根目录添加到Python路径，确保可以正确导入模块
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.settings import settings
from src.api.routers import loadfile, query, health, auth, knowledge_base, chat, evaluation, assistant, agent, monitor, storage, notes
from src.database.sql_session import engine, Base

# 创建数据库表结构
Base.metadata.create_all(bind=engine)


def create_app() -> FastAPI:
    """
    创建并配置FastAPI应用实例
    
    该工厂函数负责初始化FastAPI应用，配置CORS中间件，
    并注册所有功能模块的路由。
    
    Returns:
        FastAPI: 配置完成的FastAPI应用实例
    """
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        description="RAG System for PDF Documents"
    )

    # 配置CORS跨域中间件，允许所有来源的请求
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册各功能模块路由，按功能分类组织API接口
    app.include_router(health.router, prefix=settings.API_PREFIX + "/health", tags=["Health"])
    app.include_router(auth.router, prefix=settings.API_PREFIX + "/auth", tags=["Auth"])
    app.include_router(knowledge_base.router, prefix=settings.API_PREFIX + "/knowledge-bases", tags=["Knowledge Base"])
    app.include_router(assistant.router, prefix=settings.API_PREFIX + "/assistants", tags=["Assistant"])
    app.include_router(agent.router, prefix=settings.API_PREFIX + "/agents", tags=["Agent"])
    app.include_router(monitor.router, prefix=settings.API_PREFIX + "/monitor", tags=["Monitor"])
    app.include_router(storage.router, prefix=settings.API_PREFIX + "/storage", tags=["MinIO Storage"])
    app.include_router(chat.router, prefix=settings.API_PREFIX + "/chat", tags=["RAG Chat"])
    app.include_router(evaluation.router, prefix=settings.API_PREFIX + "/evaluations", tags=["Evaluation"])
    app.include_router(loadfile.router, prefix=settings.API_PREFIX + "/upload", tags=["File Management"])
    app.include_router(notes.router, prefix=settings.API_PREFIX + "/notes", tags=["Notes"])

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
