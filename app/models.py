from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone, timedelta

Base = declarative_base()

# Московское время (UTC+3)
MSK = timezone(timedelta(hours=3))

def get_msk_time():
    return datetime.now(MSK)

class User(Base):
    __tablename__ = "users"
    user_id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)

    pdf_files = relationship("PDFFile", back_populates="user", cascade="all, delete-orphan")
    flashcards = relationship("Flashcard", back_populates="user", cascade="all, delete-orphan")
    action_history = relationship("ActionHistory", back_populates="user", cascade="all, delete-orphan")

class PDFFile(Base):
    __tablename__ = "pdf_files"

    id = Column(Integer, primary_key=True)
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    user_id = Column(Integer, ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=get_msk_time)

    user = relationship("User", back_populates="pdf_files")
    flashcards = relationship("Flashcard", back_populates="pdf_file", cascade="all, delete-orphan")

class Flashcard(Base):
    __tablename__ = "flashcards"

    id = Column(Integer, primary_key=True)
    pdf_file_id = Column(Integer, ForeignKey('pdf_files.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    context = Column(Text)
    source = Column(String)
    # ✅ ДОБАВЛЕНА
    created_at = Column(DateTime, default=get_msk_time)

    pdf_file = relationship("PDFFile", back_populates="flashcards")
    user = relationship("User", back_populates="flashcards")

class ActionHistory(Base):
    __tablename__ = "action_history"

    id = Column(Integer, primary_key=True)
    action = Column(String(100), nullable=False)
    filename = Column(String(255))
    details = Column(Text)
    user_id = Column(Integer, ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False)
    # ✅ ДОБАВЛЕНА
    created_at = Column(DateTime, default=get_msk_time)

    user = relationship("User", back_populates="action_history")

class ProcessingStatus(Base):
    __tablename__ = "processing_status"

    id = Column(Integer, primary_key=True)
    pdf_file_id = Column(Integer, ForeignKey('pdf_files.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False)
    status = Column(String, default="processing")
    cards_count = Column(Integer, default=0)
    should_cancel = Column(Boolean, default=False)
    error_message = Column(Text, nullable=True)
    # ✅ Московское время
    created_at = Column(DateTime, default=get_msk_time)
    updated_at = Column(DateTime, default=get_msk_time, onupdate=get_msk_time)

    pdf_file = relationship("PDFFile")
    user = relationship("User")
