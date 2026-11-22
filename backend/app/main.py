"""
Main FastAPI Application Entrypoint for No2SQL.
Mounts API routes, static frontend files, enables localhost CORS,
and provides exception shielding so no internal tracebacks or paths leak to clients.
"""

import logging
import uuid
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .api.routes import router as api_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("no2sql")

app = FastAPI(
    title="No2SQL API",
    description="Ask your database any question in clear English - Course Project Demo (SCSE4041 Team Tech Goliaths)",
    version=settings.VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS: localhost only
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Global exception shielding
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    err_id = str(uuid.uuid4())
    logger.error(f"Unhandled exception (Error ID: {err_id}): {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"An unexpected internal error occurred. Please contact support with Request ID: {err_id}."
        },
    )


# Include API routes
app.include_router(api_router)

# Mount frontend static directory
frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
