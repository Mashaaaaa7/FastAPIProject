from app.database import SessionLocal
from app.models import Flashcard

db = SessionLocal()

db.query(Flashcard).delete()
db.commit()

print(f"✅ Все данные удалены из таблицы flashcards!")

db.close()
