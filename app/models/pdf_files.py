from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
from datetime import datetime


class PDFFile(Base):
    __tablename__ = "pdf_files"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, unique=True, index=True, nullable=False)
    file_size = Column(Integer, nullable=False)
    file_path = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    user_id = Column(Integer, ForeignKey("user.user_id"))

    user = relationship("User", back_populates="pdf_files")

class ActionHistory(Base):
    __tablename__ = "action_history"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(String, nullable=False)
    deck_name = Column(String, nullable=True)
    filename = Column(String, nullable=True)
    details = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    user_id = Column(Integer, ForeignKey("user.user_id"))

    user = relationship("User", back_populates="action_history")