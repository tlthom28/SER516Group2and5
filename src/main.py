import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from src.api.routes import router as api_router
from src.worker.pool import WorkerPool
from src.core.config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# shared worker pool instance — started eagerly so it's ready for tests and
# any code that imports the app without triggering the lifespan context.
worker_pool = WorkerPool(pool_size=Config.WORKER_POOL_SIZE)
worker_pool.start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start pool on startup, shut down on shutdown."""
    worker_pool.start()
    yield
    worker_pool.shutdown(wait=False)


app = FastAPI(
    title="RepoPulse API",
    description="A metrics and monitoring tool for GitHub repositories.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.state.worker_pool = worker_pool
app.include_router(api_router)
