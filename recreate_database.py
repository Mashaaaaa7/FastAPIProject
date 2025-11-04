# recreate_database.py
import os
from app.core.database import Base, engine


def recreate_database():
    print("🔄 Полное пересоздание базы данных...")

    # Удаляем старую БД
    if os.path.exists("./app.db"):
        os.remove("./app.db")
        print("✅ Старая БД удалена")

    # Создаем новую БД
    Base.metadata.create_all(bind=engine)

    # Сбрасываем автоинкремент
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM sqlite_sequence"))
        conn.commit()

    print("✅ Новая БД создана с правильной структурой")
    print("✅ Автоинкремент сброшен")
    print("🎯 Теперь ID пользователей будут начинаться с 1")


if __name__ == "__main__":
    recreate_database()