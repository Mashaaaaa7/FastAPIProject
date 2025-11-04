from sqlalchemy.orm import Session
from app.models.user import User
from app.shemas.user_shema import UserCreate
from app.core.security import hash_password, verify_password
from datetime import datetime, timezone

def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()

def create_user(db: Session, user: UserCreate):
    print(f"Создание пользователя: {user.email}")

    # Проверяем, существует ли пользователь
    db_user = get_user_by_email(db, email=user.email)
    if db_user:
        print("Пользователь уже существует")
        return None

    # Создаем нового пользователя
    try:
        hashed_password = hash_password(user.password)
        db_user = User(
            email=user.email,
            hashed_password=hashed_password,
            created_at=datetime.now(timezone.utc)
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        print(f"Пользователь создан: {db_user.id}")
        return db_user
    except Exception as e:
        db.rollback()
        print(f"Ошибка при создании пользователя: {e}")
        raise e

def authenticate_user(db: Session, email: str, password: str):
    """Аутентификация пользователя"""
    user = get_user_by_email(db, email)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user