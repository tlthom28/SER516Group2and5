import logging
import os
from contextlib import asynccontextmanager

from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

from fastapi import FastAPI
from src.api.routes import router as api_router
from src.worker.pool import WorkerPool
from src.core.config import Config


def otel_setup():
    # define metadata to describe the name of the service and environment log emits from
    resource = Resource.create({
        "service.name": os.getenv("OTEL_SERVICE_NAME", "repopulse-api"),
        "deployment.environment": os.getenv("ENV", "development")
    })

    # exporter to send logs to the grafana alloy instance
    exporter = OTLPLogExporter(
        endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://alloy:4317"),
        insecure=True,
    )

    # instantiate logging factory
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    # set logging factory globally
    set_logger_provider(logger_provider)

    # setup python logging to inherit otel logging
    handler = LoggingHandler(level=logging.DEBUG, logger_provider=logger_provider)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


# calling otel_setup() early to override default logging, do not remove
# Only initialise the gRPC-backed OTLP exporter when explicitly enabled.
# Without this guard gRPC starts background threads that crash on fork(),
# which breaks any test that uses subprocess.
if os.getenv("OTEL_ENABLED", "false").lower() == "true":
    otel_setup()

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
