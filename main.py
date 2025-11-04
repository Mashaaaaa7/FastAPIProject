from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth_routes, user_routes, pdf_routes
from app.core.database import Base, engine

app = FastAPI()

Base.metadata.create_all(bind=engine)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router, prefix="/api/auth", tags=["Auth"])
app.include_router(user_routes.router, prefix="/api/users", tags=["Users"])
app.include_router(pdf_routes.router, prefix="/api/pdf", tags=["Pdf"])