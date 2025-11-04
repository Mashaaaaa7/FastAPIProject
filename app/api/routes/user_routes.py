# app/api/routes/user_routes.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.user import User
from app.models.pdf_files import PDFFile, ActionHistory
from fastapi.security import OAuth2PasswordBearer
from app.shemas.user_shema import UserResponse

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
router = APIRouter()

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """Проверяет токен и возвращает текущего пользователя"""
    from app.core.security import decode_access_token

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Неверный токен")
    email = payload.get("sub")
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user

@router.get("/me", response_model=UserResponse)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получить профиль текущего пользователя"""
    return current_user

@router.delete("/me", status_code=status.HTTP_200_OK)
async def delete_my_profile(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """
    Удалить профиль текущего пользователя и все связанные данные
    """
    try:
        # Сохраняем информацию для ответа
        user_info = {
            "user_id": current_user.user_id,
            "email": current_user.email
        }

        print(f"🗑️ Начинаем удаление пользователя: {current_user.email} (ID: {current_user.user_id})")

        # 1. Удаляем все PDF файлы пользователя
        pdf_count = db.query(PDFFile).filter(PDFFile.user_id == current_user.user_id).delete()
        print(f"✅ Удалено PDF файлов: {pdf_count}")

        # 2. Удаляем всю историю действий пользователя
        history_count = db.query(ActionHistory).filter(ActionHistory.user_id == current_user.user_id).delete()
        print(f"✅ Удалено записей истории: {history_count}")

        # 3. Удаляем самого пользователя
        db.delete(current_user)
        db.commit()

        print(f"🎉 Профиль пользователя {current_user.email} полностью удален")

        return {
            "message": "Профиль успешно удален",
            "deleted_user": user_info,
            "deleted_files_count": pdf_count,
            "deleted_history_count": history_count
        }

    except Exception as e:
        db.rollback()
        print(f"❌ Ошибка при удалении профиля: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при удалении профиля: {str(e)}"
        )