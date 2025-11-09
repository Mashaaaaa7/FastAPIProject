from sqlalchemy.orm import Session
from app import models
import json

def save_flashcards(db: Session, pdf_file_id: int, user_id: int, flashcards: list):
    """Сохраняет карточки в БД и JSON"""
    try:
        # Сохраняем в БД
        for card in flashcards:
            flashcard = models.Flashcard(
                pdf_file_id=pdf_file_id,
                user_id=user_id,
                question=card['question'],
                answer=card['answer'],
                context=card.get('context', ''),
                source=card.get('source', '')
            )
            db.add(flashcard)

        db.commit()

        # Сохраняем в JSON файл
        pdf_file = db.query(models.PDFFile).filter(models.PDFFile.id == pdf_file_id).first()
        if pdf_file:
            json_path = pdf_file.file_path.replace('.pdf', '_cards.json')
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(flashcards, f, ensure_ascii=False, indent=2)

        return True
    except Exception as e:
        db.rollback()
        print(f"Error saving flashcards: {e}")
        raise


def get_flashcards_by_pdf(db: Session, pdf_file_id: int, user_id: int):
    """Получает карточки по PDF файлу"""
    return db.query(models.Flashcard).filter(
        models.Flashcard.pdf_file_id == pdf_file_id,
        models.Flashcard.user_id == user_id
    ).all()

def delete_flashcards_by_pdf(db: Session, pdf_file_id: int):
    """Удаляет карточки по PDF файлу"""
    db.query(models.Flashcard).filter(
        models.Flashcard.pdf_file_id == pdf_file_id
    ).delete()
    db.commit()


def add_action(db: Session, action: str, filename: str, user_id: int, details: str = None):
    """Добавляет действие в историю"""
    try:
        if details is None:
            details = f"{action} file: {filename}"

        record = models.ActionHistory(
            action=action,
            filename=filename,
            details=details,  # ← ЭТА СТРОКА
            user_id=user_id
        )
        db.add(record)
        db.commit()
        return record
    except Exception as e:
        db.rollback()
        print(f"Error adding action: {e}")
        raise

def get_history(db: Session, user_id: int):
    """Получает историю действий пользователя"""
    return db.query(models.ActionHistory).filter(
        models.ActionHistory.user_id == user_id
    ).order_by(models.ActionHistory.created_at.desc()).all()