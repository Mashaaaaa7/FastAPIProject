import logging
import os
from datetime import datetime
from typing import Optional
import pytz

from fastapi import APIRouter, UploadFile, File, HTTPException, Header, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.pdf_files import PDFFile, ActionHistory
from app.models.user import User
from app.api.routes.user_routes import get_current_user

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

router = APIRouter()


def get_user_timezone_from_ip(request: Request):
    """Определяет часовой пояс по IP адресу (упрощенная версия)"""
    try:
        client_ip = request.client.host

        # Если локальный IP, используем дефолтный (можно изменить на нужный)
        if client_ip in ['127.0.0.1', 'localhost']:
            return 'Europe/Moscow'  # Или другой дефолтный часовой пояс

        # Для простоты используем дефолтный часовой пояс
        # В реальном приложении можно использовать API геолокации
        return 'Europe/Moscow'

    except:
        return 'UTC + 3'


def get_user_time(timezone_str: str):
    """Возвращает текущее время в указанном часовом поясе"""
    try:
        user_tz = pytz.timezone(timezone_str)
        return datetime.now(user_tz)
    except:
        # Если часовой пояс невалидный, используем UTC
        return datetime.now(pytz.UTC)


@router.post("/upload")
async def upload_pdf(
        file: UploadFile = File(...),
        request: Request = None,
        authorization: Optional[str] = Header(None),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # Определяем часовой пояс
    if request:
        user_timezone = get_user_timezone_from_ip(request)
    else:
        # Если request не передан, используем время UTC
        user_timezone = 'UTC + 3'

    user_time = get_user_time(user_timezone)

    logger.info(f"📨 Получен файл: {file.filename} от пользователя: {current_user.email} (Timezone: {user_timezone})")

    if not file.filename:
        raise HTTPException(400, "No file provided")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are allowed")

    try:
        existing_file = db.query(PDFFile).filter(
            PDFFile.filename == file.filename,
            PDFFile.user_id == current_user.id
        ).first()

        if existing_file:
            raise HTTPException(400, "File with this name already exists")

        # Создаем папку для пользователя
        user_upload_dir = os.path.join(UPLOAD_DIR, str(current_user.id))
        os.makedirs(user_upload_dir, exist_ok=True)

        # Сохраняем файл
        file_path = os.path.join(user_upload_dir, file.filename)

        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        file_size = len(content)

        # Сохраняем в БД с ВРЕМЕНЕМ ПОЛЬЗОВАТЕЛЯ
        file_info = PDFFile(
            filename=file.filename,
            file_size=file_size,
            file_path=file_path,
            user_id=current_user.id,
            created_at=user_time  # ВРЕМЯ ПОЛЬЗОВАТЕЛЯ
        )
        db.add(file_info)
        db.commit()
        db.refresh(file_info)

        # История с ВРЕМЕНЕМ ПОЛЬЗОВАТЕЛЯ
        history_record = ActionHistory(
            action="upload_pdf",
            filename=file.filename,
            details=f"Uploaded PDF file: {file.filename} ({file_size} bytes)",
            user_id=current_user.id,
            timestamp=user_time  # ВРЕМЯ ПОЛЬЗОВАТЕЛЯ
        )
        db.add(history_record)
        db.commit()

        return {
            "success": True,
            "message": f"File {file.filename} uploaded successfully",
            "filename": file.filename,
            "user_time": user_time.isoformat(),  # Возвращаем время пользователя
            "user_timezone": user_timezone
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        db.rollback()
        raise HTTPException(500, f"Server error: {str(e)}")


@router.get("/decks")
def list_decks(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    user_files = db.query(PDFFile).filter(
        PDFFile.user_id == current_user.id
    ).all()

    files_data = [
        {
            "name": file.filename,
            "file_size": file.file_size,
            "created_at": file.created_at.strftime("%Y-%m-%d %H:%M:%S")
        }
        for file in user_files
    ]

    return {"success": True, "decks": files_data}


@router.get("/history")
async def get_history(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    user_history = db.query(ActionHistory).filter(
        ActionHistory.user_id == current_user.id
    ).order_by(ActionHistory.timestamp.desc()).all()

    history_data = [
        {
            "id": record.id,
            "action": record.action,
            "deck_name": record.deck_name,
            "filename": record.filename,
            "timestamp": record.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "details": record.details
        }
        for record in user_history
    ]

    return {
        "success": True,
        "history": history_data,
        "total": len(history_data)
    }


@router.post("/decks/{deck_name}/cards")
async def create_cards(
        deck_name: str,
        request: Request = None,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    file_exists = db.query(PDFFile).filter(
        PDFFile.filename == deck_name,
        PDFFile.user_id == current_user.id
    ).first()

    if not file_exists:
        raise HTTPException(404, "PDF file not found")

    # Определяем часовой пояс для времени
    if request:
        user_timezone = get_user_timezone_from_ip(request)
    else:
        user_timezone = 'UTC'

    user_time = get_user_time(user_timezone)

    # История с ВРЕМЕНЕМ ПОЛЬЗОВАТЕЛЯ
    history_record = ActionHistory(
        action="create_cards",
        deck_name=deck_name,
        details=f"Created flashcards from deck: {deck_name}",
        user_id=current_user.id,
        timestamp=user_time  # ВРЕМЯ ПОЛЬЗОВАТЕЛЯ
    )
    db.add(history_record)
    db.commit()

    # Демо-карточки
    cards = [
        {"id": 1, "question": "Что такое React?", "answer": "Библиотека для UI", "deck_name": deck_name},
        {"id": 2, "question": "Что такое компонент?", "answer": "Переиспользуемая часть UI", "deck_name": deck_name},
        {"id": 3, "question": "Что такое useState?", "answer": "Хук для состояния в React", "deck_name": deck_name},
    ]

    return {"success": True, "cards": cards, "deck_name": deck_name, "total": len(cards)}


@router.delete("/decks/{deck_name}")
async def delete_deck(
        deck_name: str,
        request: Request = None,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # Находим файл в БД
    file_record = db.query(PDFFile).filter(
        PDFFile.filename == deck_name,
        PDFFile.user_id == current_user.id
    ).first()

    if not file_record:
        raise HTTPException(404, "PDF file not found")

    try:
        # Удаляем ТОЛЬКО физический файл из папки uploads
        file_path = file_record.file_path
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"🗑️ Физический файл удален: {file_path}")
        else:
            logger.warning(f"⚠️ Физический файл не найден: {file_path}")

        # Определяем часовой пояс для времени
        if request:
            user_timezone = get_user_timezone_from_ip(request)
        else:
            user_timezone = 'UTC'

        user_time = get_user_time(user_timezone)

        # Сохраняем историю с ВРЕМЕНЕМ ПОЛЬЗОВАТЕЛЯ
        history_record = ActionHistory(
            action="delete_deck",
            deck_name=deck_name,
            details=f"Deleted physical file: {deck_name} (record kept in DB)",
            user_id=current_user.id,
            timestamp=user_time  # ВРЕМЯ ПОЛЬЗОВАТЕЛЯ
        )
        db.add(history_record)
        db.commit()

        return {"success": True, "message": f"File {deck_name} deleted (physical file only)"}

    except Exception as e:
        logger.error(f"❌ Ошибка удаления: {e}")
        db.rollback()
        raise HTTPException(500, f"Server error: {str(e)}")