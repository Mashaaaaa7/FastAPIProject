# delete_all_users.py
from sqlalchemy import text
from app.core.database import SessionLocal
from app.models.pdf_files import ActionHistory, PDFFile
from app.models.user import User


def delete_all_users_and_data():
    """Удаляет всех пользователей и все связанные данные"""
    with SessionLocal() as session:
        try:
            print("🗑️ Начинаем удаление всех данных...")

            # 1. Удаляем все PDF файлы
            pdf_count = session.query(PDFFile).count()
            session.query(PDFFile).delete()
            print(f"✅ Удалено PDF файлов: {pdf_count}")

            # 2. Удаляем всю историю действий
            history_count = session.query(ActionHistory).count()
            session.query(ActionHistory).delete()
            print(f"✅ Удалено записей истории: {history_count}")

            # 3. Удаляем всех пользователей
            user_count = session.query(User).count()
            session.query(User).delete()
            print(f"✅ Удалено пользователей: {user_count}")

            # 4. Сбрасываем автоинкремент
            session.execute(text("DELETE FROM sqlite_sequence"))
            print("✅ Автоинкремент сброшен")

            session.commit()
            print("🎉 Все данные успешно удалены!")

            return {
                "deleted_users": user_count,
                "deleted_pdf_files": pdf_count,
                "deleted_history": history_count
            }

        except Exception as e:
            session.rollback()
            print(f"❌ Ошибка при удалении: {e}")
            raise


if __name__ == "__main__":
    delete_all_users_and_data()