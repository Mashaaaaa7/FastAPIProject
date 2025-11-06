from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine
from app.models import Base

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="PDF Processing API",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Маршруты
from app.endpoints import pdf, user

app.include_router(user.router, prefix="/api/auth", tags=["auth"])
app.include_router(pdf.router, prefix="/api", tags=["files"])

@app.get("/")
def read_root():
    return {"message": "PDF Processing API"}
