# app/models/user.py
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base

class User(Base):
    __tablename__ = "user"

    user_id = Column(Integer, primary_key=True, index=True, autoincrement=True)  # ✅ Добавьте autoincrement
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    timezone = Column(String, default="UTC")
    created_at = Column(DateTime, default=datetime.utcnow)

    pdf_files = relationship("PDFFile", back_populates="user")
    action_history = relationship("ActionHistory", back_populates="user")

    @property
    def id(self):
        return self.user_id