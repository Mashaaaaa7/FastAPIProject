import threading
import uuid
import os
import sys
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.models import User, PDFFile
from app.database import get_db, SessionLocal
from app import crud, models
from app.services.qa_generator import QAGenerator

router = APIRouter()

qa_generator = None


def get_qa_generator():
    """Инициализирует QA генератор (singleton)"""
    global qa_generator
    if qa_generator is None:
        print("🔧 Инициализирую QAGenerator...", flush=True)
        sys.stdout.flush()
        qa_generator = QAGenerator()
    return qa_generator


# ============================================================================
# ✅ BACKGROUND FUNCTION: Process PDF in thread
# ============================================================================
def process_pdf_background(
        file_id: int,
        file_path: str,
        filename: str,
        user_id: int,
        max_cards: int,
        status_id: int
):
    """Обработка PDF в отдельном потоке с поддержкой отмены"""

    # ✅ СОЗДАЁМ НОВУЮ СЕССИЮ для потока
    db = SessionLocal()

    try:
        print(f"🔄 Начинаю обработку {filename}...", flush=True)
        sys.stdout.flush()

        # ✅ Инициализируем генератор
        qa_gen = get_qa_generator()

        # ✅ Передаём db в функцию с поддержкой отмены
        flashcards = qa_gen.process_pdf_with_cancellation(
            file_path, max_cards, db, status_id
        )

        if flashcards:
            # ✅ Сохраняем карточки в БД
            for card_data in flashcards:
                flashcard = models.Flashcard(
                    pdf_file_id=file_id,
                    user_id=user_id,
                    question=card_data["question"],
                    answer=card_data["answer"],
                    context=card_data.get("context", ""),
                    source=card_data.get("source", "")
                )
                db.add(flashcard)

            db.commit()
            print(f"✅ Сохранено {len(flashcards)} карточек в БД", flush=True)
        else:
            print(f"⚠️ Карточки не созданы для {filename}", flush=True)

        # ✅ Обновляем статус обработки
        status = db.query(models.ProcessingStatus).filter(
            models.ProcessingStatus.id == status_id
        ).first()

        if status:
            if status.should_cancel:
                status.status = "cancelled"
                print(f"⛔ Обработка отменена для {filename}", flush=True)
            else:
                status.status = "completed"
                status.cards_count = len(flashcards) if flashcards else 0
                print(f"✅ Готово: {len(flashcards)} карточек", flush=True)

            db.commit()

    except Exception as e:
        print(f"❌ ОШИБКА в потоке: {str(e)}", flush=True)
        import traceback
        traceback.print_exc()

        try:
            status = db.query(models.ProcessingStatus).filter(
                models.ProcessingStatus.id == status_id
            ).first()
            if status:
                status.status = "failed"
                status.error_message = str(e)[:500]
                db.commit()
                print(f"❌ Статус обновлен на 'failed'", flush=True)
        except Exception as e2:
            print(f"❌ Ошибка обновления статуса: {e2}", flush=True)

    finally:
        # ✅ ЗАКРЫВАЕМ СЕССИЮ
        db.close()
        sys.stdout.flush()


# ============================================================================
# ✅ ENDPOINT 1: Upload PDF
# ============================================================================
@router.post("/upload-pdf")
async def upload_pdf(
        file: UploadFile = File(...),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Загружает PDF файл"""
    try:
        # ✅ Создаём папку для пользователя
        folder = f"uploads/{user.user_id}/"
        os.makedirs(folder, exist_ok=True)

        # ✅ Сохраняем файл с уникальным именем
        file_ext = os.path.splitext(file.filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        file_path = os.path.join(folder, unique_filename)

        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)

        # ✅ Сохраняем в БД
        db_file = PDFFile(
            file_name=file.filename,
            file_path=file_path,
            user_id=user.user_id
        )
        db.add(db_file)
        db.commit()
        db.refresh(db_file)

        # ✅ Логируем действие
        try:
            crud.add_action(
                db=db,
                action="upload",
                filename=file.filename,
                details=f"Uploaded {len(contents)} bytes",
                user_id=user.user_id
            )
        except Exception as e:
            print(f"⚠️ Warning: action not logged: {e}", flush=True)

        print(f"✅ Файл загружен: {file.filename} (ID: {db_file.id})", flush=True)

        return {
            "file_name": file.filename,
            "file_id": db_file.id,
            "message": "File uploaded successfully"
        }

    except Exception as e:
        db.rollback()
        print(f"❌ ERROR in upload_pdf: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ✅ ENDPOINT 2: Start Processing PDF
# ============================================================================
@router.post("/process-pdf/{file_id}")
async def process_pdf(
        file_id: int,
        max_cards: int = 10,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Запускает обработку PDF в фоновом потоке"""
    try:
        # ✅ Проверяем что файл существует и принадлежит пользователю
        pdf_file = db.query(PDFFile).filter(
            PDFFile.id == file_id,
            PDFFile.user_id == user.user_id,
            PDFFile.is_deleted == False
        ).first()

        if not pdf_file:
            raise HTTPException(status_code=404, detail="PDF not found")

        # ✅ Создаём запись статуса обработки
        status = models.ProcessingStatus(
            pdf_file_id=file_id,
            user_id=user.user_id,
            status="processing"
        )
        db.add(status)
        db.commit()
        db.refresh(status)

        print(f"🧵 Запускаю обработку файла {pdf_file.file_name} (status_id={status.id})", flush=True)

        # ✅ Запускаем в ОТДЕЛЬНОМ ПОТОКЕ (НЕ требует Celery!)
        thread = threading.Thread(
            target=process_pdf_background,
            args=(
                file_id,
                pdf_file.file_path,
                pdf_file.file_name,
                user.user_id,
                max_cards,
                status.id
            ),
            daemon=True
        )
        thread.start()

        return {
            "success": True,
            "message": f"Processing started for {pdf_file.file_name}",
            "status_id": status.id
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"❌ ERROR in process_pdf: {str(e)}", flush=True)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ✅ ENDPOINT 3: Check Processing Status
# ============================================================================
@router.get("/processing-status/{file_id}")
async def check_processing_status(
        file_id: int,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Проверяет статус обработки PDF"""
    try:
        # ✅ Проверяем что файл принадлежит пользователю
        pdf_file = db.query(PDFFile).filter(
            PDFFile.id == file_id,
            PDFFile.user_id == user.user_id
        ).first()

        if not pdf_file:
            raise HTTPException(status_code=404, detail="PDF not found")

        # ✅ Получаем последний статус обработки
        status = db.query(models.ProcessingStatus).filter(
            models.ProcessingStatus.pdf_file_id == file_id,
            models.ProcessingStatus.user_id == user.user_id
        ).order_by(models.ProcessingStatus.created_at.desc()).first()

        if not status:
            return {
                "success": True,
                "status": "not_started",
                "cards_count": 0
            }

        return {
            "success": True,
            "status": status.status,  # "processing", "completed", "failed", "cancelled"
            "cards_count": status.cards_count or 0,
            "created_at": status.created_at.isoformat() if status.created_at else None
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ ERROR in check_processing_status: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ✅ ENDPOINT 4: Get Generated Cards
# ============================================================================
@router.get("/cards/{file_id}")
async def get_cards(
        file_id: int,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Получает сгенерированные карточки для PDF"""
    try:
        # ✅ Проверяем что файл принадлежит пользователю
        pdf_file = db.query(PDFFile).filter(
            PDFFile.id == file_id,
            PDFFile.user_id == user.user_id
        ).first()

        if not pdf_file:
            raise HTTPException(status_code=404, detail="PDF not found")

        # ✅ Получаем карточки
        flashcards = crud.get_flashcards_by_pdf(db, file_id, user.user_id)

        return {
            "success": True,
            "file_name": pdf_file.file_name,
            "cards": [
                {
                    "id": card.id,
                    "question": card.question,
                    "answer": card.answer,
                    "context": card.context or "",
                    "source": card.source or "",
                    "created_at": card.created_at.isoformat() if card.created_at else None
                }
                for card in flashcards
            ],
            "total": len(flashcards)
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ ERROR in get_cards: {str(e)}", flush=True)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ✅ ENDPOINT 5: List User's PDFs
# ============================================================================
@router.get("/pdfs")
async def list_user_pdfs(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Получает список активных PDF файлов пользователя"""
    try:
        # ✅ Получаем только не удалённые файлы
        pdf_files = db.query(PDFFile).filter(
            PDFFile.user_id == user.user_id,
            PDFFile.is_deleted == False
        ).all()

        return {
            "success": True,
            "pdfs": [
                {
                    "id": pdf.id,
                    "name": pdf.file_name,
                    "file_size": os.path.getsize(pdf.file_path) if os.path.exists(pdf.file_path) else 0
                }
                for pdf in pdf_files
            ],
            "total": len(pdf_files)
        }

    except Exception as e:
        print(f"❌ ERROR in list_user_pdfs: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ✅ ENDPOINT 6: Get Action History
# ============================================================================
@router.get("/history")
async def get_history(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Получает историю действий пользователя"""
    try:
        # ✅ Получаем действия пользователя
        actions = crud.get_history(db, user.user_id)

        history_data = [
            {
                "id": action.id,
                "action": action.action,
                "filename": action.filename or "unknown",
                "details": action.details or f"{action.action} file",
                "timestamp": action.created_at.isoformat() if action.created_at else None,
                "created_at": action.created_at.isoformat() if action.created_at else None
            }
            for action in actions
        ]

        return {
            "success": True,
            "history": history_data,
            "total": len(history_data)
        }

    except Exception as e:
        print(f"❌ ERROR in get_history: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ✅ ENDPOINT 7: Delete PDF (Soft Delete)
# ============================================================================
@router.delete("/delete-file/{file_id}")
async def delete_pdf(
        file_id: int,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Мягкое удаление PDF - помечает как удалённый в БД, физический файл остаётся"""
    try:
        # ✅ Проверяем что файл существует и принадлежит пользователю
        pdf_file = db.query(PDFFile).filter(
            PDFFile.id == file_id,
            PDFFile.user_id == user.user_id,
            PDFFile.is_deleted == False
        ).first()

        if not pdf_file:
            raise HTTPException(status_code=404, detail="PDF not found")

        # ✅ Помечаем как удалённый (НЕ удаляем из БД!)
        pdf_file.is_deleted = True
        db.commit()

        print(f"🗑️ File {pdf_file.file_name} marked as deleted (is_deleted=True)", flush=True)

        # ✅ Логируем действие
        try:
            crud.add_action(
                db=db,
                action="delete",
                filename=pdf_file.file_name,
                details=f"Deleted file {pdf_file.file_name}",
                user_id=user.user_id
            )
        except Exception as e:
            print(f"⚠️ Warning: delete action not logged: {e}", flush=True)

        return {
            "success": True,
            "message": f"File {pdf_file.file_name} deleted"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"❌ ERROR in delete_pdf: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ✅ ENDPOINT 8: Cancel Processing
# ============================================================================
@router.post("/cancel-processing/{file_id}")
async def cancel_processing(
        file_id: int,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Отмена обработки PDF - устанавливает флаг should_cancel"""
    try:
        # ✅ Проверяем что файл принадлежит пользователю
        pdf_file = db.query(PDFFile).filter(
            PDFFile.id == file_id,
            PDFFile.user_id == user.user_id
        ).first()

        if not pdf_file:
            raise HTTPException(status_code=404, detail="PDF not found")

        # ✅ Получаем текущий статус обработки
        status = db.query(models.ProcessingStatus).filter(
            models.ProcessingStatus.pdf_file_id == file_id,
            models.ProcessingStatus.user_id == user.user_id,
            models.ProcessingStatus.status == "processing"
        ).first()

        if not status:
            raise HTTPException(status_code=404, detail="Processing not found or already finished")

        # ✅ Устанавливаем флаг отмены
        status.should_cancel = True
        db.commit()

        print(f"⛔ Cancel requested for file {file_id}", flush=True)

        return {
            "success": True,
            "message": "Processing cancelled"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"❌ ERROR in cancel_processing: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))