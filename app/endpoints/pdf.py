from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from app.auth import get_current_user
from app.models import User, PDFFile
from app.database import SessionLocal
from app import crud
import os

router = APIRouter()


@router.post("/upload-pdf")
async def upload_pdf(
        file: UploadFile = File(...),
        user: User = Depends(get_current_user)
):
    db = SessionLocal()
    try:
        folder = f"uploads/{user.user_id}/"
        os.makedirs(folder, exist_ok=True)
        file_path = f"{folder}{file.filename}"

        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)

        # Сохраняем в БД
        db_file = crud.add_pdf(
            db=db,
            file_name=file.filename,
            file_path=file_path,
            user_id=user.user_id
        )

        crud.add_action(
            db=db,
            action="upload",
            filename=file.filename,
            user_id=user.user_id
        )

        return {
            "file_name": file.filename,
            "file_id": db_file.id,
            "message": "File uploaded successfully"
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/cards/{file_name}")
async def get_cards(file_name: str, user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        # Ищем файл по названию и проверяем, что он принадлежит пользователю
        pdf_file = db.query(PDFFile).filter(
            PDFFile.file_name == file_name,
            PDFFile.user_id == user.user_id
        ).first()

        if not pdf_file:
            raise HTTPException(
                status_code=404,
                detail=f"PDF file '{file_name}' not found"
            )

        # Логируем просмотр
        crud.add_action(
            db=db,
            action="view",
            filename=file_name,
            user_id=user.user_id
        )

        # Заглушка: три карточки
        return [
            {
                "question": "Что такое Python?",
                "answer": "Язык программирования"
            },
            {
                "question": "Что такое FastAPI?",
                "answer": "Web framework"
            },
            {
                "question": "Что такое JWT?",
                "answer": "Токен аутентификации"
            }
        ]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/history")
async def get_history(user: User = Depends(get_current_user)):
    """Получить историю действий пользователя из БД"""
    db = SessionLocal()
    try:
        actions = crud.get_history(db, user.user_id)

        history_data = [
            {
                "id": action.id,
                "action": action.action,
                "filename": action.filename or "unknown",
                "timestamp": action.created_at.isoformat(),
                "details": f"{action.action} file: {action.filename}"
            }
            for action in actions
        ]

        return {
            "success": True,
            "history": history_data,
            "total": len(history_data)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
