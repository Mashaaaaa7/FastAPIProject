import re
import unicodedata
from typing import List, Dict
from transformers import pipeline
import pdfplumber
import torch
from sqlalchemy.orm import Session
from app import models

class QAGenerator:
    def __init__(self, use_gpt: bool = False):
        self.device = 0 if torch.cuda.is_available() else -1
        self.use_gpt = use_gpt
        print("⏳ Загружаю русскую модель...", flush=True)

        self.generator = pipeline(
            "text2text-generation",
            model="cointegrated/rut5-small",
            device=self.device,
            torch_dtype=torch.float32
        )
        print("✅ Модель загружена!", flush=True)

    def clean_text(self, text: str) -> str:
        """Очищает текст от артефактов"""
        if not text:
            return ""
        text = ''.join(ch for ch in text if unicodedata.category(ch)[0] != 'C' or ch in '\n\t')
        text = re.sub(r'[>~<•»«„"\[\]{}()_\-–—]+', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def extract_meaningful_text(self, file_path: str) -> List[Dict]:
        """Извлекает осмысленные фрагменты"""
        chunks = []
        try:
            with pdfplumber.open(file_path) as pdf:
                print(f"📄 PDF имеет {len(pdf.pages)} страниц")

                for i, page in enumerate(pdf.pages):
                    raw_text = page.extract_text()
                    if not raw_text:
                        continue

                    text = self.clean_text(raw_text)
                    if len(text) < 100:
                        continue

                    text = re.sub(r'^\d{2}\.\d{2}\.\d{4}.*?Colab\s*', '', text)
                    text = re.sub(r'https?://[^\s]+', '', text)
                    text = re.sub(r'\d{4}.*?ipynb.*?Colab', '', text, flags=re.IGNORECASE)

                    paragraphs = [p.strip() for p in text.split('\n') if len(p.strip()) > 50]

                    for para in paragraphs:
                        chunks_from_para = self._split_into_chunks(para)
                        chunks.extend(chunks_from_para)

            chunks = [c for c in chunks if not any(
                bad in c['text'].lower() for bad in ['ipynb', 'colab', 'http', '©', '®']
            )]

            print(f"📊 Найдено {len(chunks)} содержательных фрагментов")
            return chunks
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return []

    def _split_into_chunks(self, text: str) -> List[Dict]:
        """Разбивает текст на смысловые куски"""
        chunks = []
        sentences = re.split(r'[.!?]+\s+', text)

        combined = []
        current = ""

        for sent in sentences:
            sent = sent.strip()
            if not sent or len(sent) < 5:
                continue

            current += sent + ". "

            if len(current.split()) >= 12:
                combined.append(current.strip())
                current = ""

        if current.strip():
            combined.append(current.strip())

        for chunk_text in combined:
            if len(chunk_text) > 60:
                chunks.append({
                    "text": chunk_text,
                    "page": 0,
                    "word_count": len(chunk_text.split())
                })

        return chunks

    def _clean_question(self, text: str) -> str:
        """Очищает вопрос от мусора"""
        text = re.sub(r'^напишите вопрос.*?:\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^вопрос.*?:\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^на основе.*?:\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^создайте.*?:\s*', '', text, flags=re.IGNORECASE)
        text = text.rstrip('.,;:')

        if text:
            text = text[0].upper() + text[1:].lower()

        if text and not text.endswith('?'):
            text += '?'

        return text.strip()

    def _generate_question_rut5(self, answer: str) -> str:
        """Генерирует вопрос через RuT5"""
        try:
            text_sample = answer[:250]
            prompt = f"Создайте вопрос к тексту: {text_sample}"

            result = self.generator(
                prompt,
                max_new_tokens=40,
                num_beams=3,
                temperature=0.6
            )

            question = self.clean_text(result[0]['generated_text']).strip()
            question = self._clean_question(question)

            if (15 < len(question) < 120 and '?' in question and
                    not question.lower().startswith('напишите') and
                    not question.lower().startswith('создайте')):
                return question

            return None
        except Exception as e:
            print(f"⚠️ RuT5 ошибка: {e}")
            return None

    def _generate_universal_question(self, answer: str) -> str:
        """Улучшенный fallback"""
        words = answer.split()
        answer_lower = answer.lower()

        bad_words = {
            'это', 'для', 'при', 'как', 'что', 'в', 'по', 'на', 'с', 'и', 'или', 'то',
            'был', 'была', 'были', 'быть', 'являются', 'является', 'есть', 'имели',
            'имеют', 'находится', 'находились', 'важный', 'важная', 'главный', 'новый',
            'процесс', 'великого', 'например', 'несмотря', 'главные', 'местное',
            'влияние', 'административное', 'уезды', 'екатерины', 'система', 'реформа'
        }

        idx = 0
        while idx < len(words) and words[idx].lower() in bad_words:
            idx += 1

        remaining_words = words[idx:]

        key_phrase = None
        for w in remaining_words[:15]:
            w_lower = w.lower().rstrip(',:;.')
            if (len(w_lower) > 5 and w[0].isupper() and w_lower not in bad_words):
                key_phrase = w_lower
                break

        if not key_phrase:
            return None

        if any(word in answer_lower for word in ['оказала', 'привел', 'вызва']):
            return f"Какое воздействие имел {key_phrase}?"
        elif any(word in answer_lower for word in ['развив', 'эволюц', 'преобразов']):
            return f"Как происходило развитие {key_phrase}?"
        elif any(word in answer_lower for word in ['привела', 'послужила', 'способствова']):
            return f"Какие факторы способствовали {key_phrase}?"
        elif any(word in answer_lower for word in ['играла', 'выполня', 'служила', 'роль']):
            return f"Какую роль выполнял {key_phrase}?"
        elif any(word in answer_lower for word in ['содержит', 'включает']):
            return f"Из чего состоит {key_phrase}?"
        elif any(word in answer_lower for word in ['представляет', 'явлением']):
            return f"Что такое {key_phrase}?"
        elif any(word in answer_lower for word in ['ввел', 'введен', 'подписать']):
            return f"Что сделал {key_phrase}?"

        return None

    def _is_corrupted_text(self, text: str) -> bool:
        """Проверяет, не повреждён ли текст"""
        if any(pattern in text for pattern in [
            'znp', 'Zogitp', 'modelnp', 'znà', 'sà', 'ру=о', 'nоrистической'
        ]):
            return True

        if text.count('=') > 2 or text.count('?') > 1:
            return True

        if re.search(r'[а-яА-Я][a-zA-Z]|[a-zA-Z][а-яА-Я]', text):
            return True

        return False

    def _is_valid_question(self, question: str) -> bool:
        """Проверяет валидность вопроса"""
        if not question or not question.endswith('?'):
            return False

        if len(question) < 12 or len(question) > 150:
            return False

        words = question.split()
        if len(words) < 3:
            return False

        bad_patterns = [
            r'^в обмен на.*\?$',
            r'^в первые.*\?$',
            r'^из.*\?$',
            r'^на.*\?$',
        ]

        for pattern in bad_patterns:
            if re.search(pattern, question.lower()):
                return False

        good_starts = ['что', 'как', 'какой', 'какие', 'кто', 'где', 'когда', 'почему', 'зачем', 'чем', 'из чего']

        first_word = words[0].lower().rstrip('?,.:;')
        if not first_word in good_starts:
            return False

        if re.search(r'что сделал[а]? (управлений?|период|система|революц)\?', question, re.IGNORECASE):
            return False

        if 'оказал' in question.lower() and 'период' in question.lower():
            return False

        return True

    def generate_qa_pair(self, context: str) -> Dict:
        """Генерирует QA пару с полной фильтрацией"""
        try:
            context_clean = self.clean_text(context[:700])
            context_clean = re.sub(r'\s+', ' ', context_clean).strip()

            if len(context_clean) < 120:
                return None

            if self._is_corrupted_text(context_clean):
                return None

            if any(word in context_clean.lower() for word in ['код', 'import', 'def ']):
                return None

            sentences = [s.strip() for s in re.split(r'[.!?]+', context_clean)]
            candidate_sents = [s for s in sentences if len(s.split()) >= 12 and len(s) > 100]

            if not candidate_sents:
                return None

            answer = candidate_sents[0]

            question = self._generate_question_rut5(answer)

            if not question:
                question = self._generate_universal_question(answer)

            if not question or not self._is_valid_question(question):
                return None

            answer = re.sub(r'\s+', ' ', answer).strip()
            question = re.sub(r'\s+', ' ', question).strip()

            if len(question) > 15 and len(answer) > 100:
                return {
                    "question": question,
                    "answer": answer,
                    "context": context_clean[:150]
                }

            return None

        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
            return None

    def process_pdf_with_cancellation(self, file_path: str, max_cards: int, db: Session, status_id: int) -> List[Dict]:
        """Обрабатывает PDF - генерирует НЕ БОЛЬШЕ max_cards уникальных карточек"""
        print(f"\n🔄 Начинаю обработку {file_path}...")
        print(f"🎯 Максимум: {max_cards} карточек (не превысим этот лимит)")

        chunks = self.extract_meaningful_text(file_path)

        if not chunks:
            print("❌ Не найдено подходящих текстовых фрагментов!")
            return []

        print(f"✅ Найдено {len(chunks)} содержательных фрагментов")

        chunks.sort(key=lambda x: abs(x['word_count'] - 25))
        flashcards = []
        seen_questions = set()

        for chunk in chunks:
            if len(flashcards) >= max_cards:
                print(f"🛑 Лимит достигнут: {len(flashcards)} = {max_cards}")
                break

            # Проверка отмены
            if db is not None:
                try:
                    status = db.query(models.ProcessingStatus).filter(
                        models.ProcessingStatus.id == status_id
                    ).first()

                    if status and status.should_cancel:
                        print(f"⛔ Обработка отменена пользователем")
                        break
                except Exception as e:
                    print(f"⚠️ Ошибка проверки флага отмены: {e}")

            qa_pair = self.generate_qa_pair(chunk['text'])

            if qa_pair:
                question = qa_pair["question"]

                if question not in seen_questions:
                    seen_questions.add(question)

                    flashcard = {
                        "question": question,
                        "answer": qa_pair["answer"],
                        "context": qa_pair["context"],
                        "source": qa_pair.get("source", "")
                    }
                    flashcards.append(flashcard)
                    print(f"  ✅ [{len(flashcards)}/{max_cards}] {question[:60]}...")

                    if len(flashcards) >= max_cards:
                        print(f"🛑 Лимит достигнут: {len(flashcards)} карточек")
                        break

        print(f"✅ Итого: {len(flashcards)} карточек (лимит: {max_cards})")

        if len(flashcards) > max_cards:
            print(f"⚠️ Превышен лимит! Обрезаю до {max_cards}")
            flashcards = flashcards[:max_cards]

        return flashcards

    def process_pdf(self, file_path: str, max_cards: int = 10) -> List[Dict]:
        """Обрабатывает PDF (без отмены)"""
        return self.process_pdf_with_cancellation(file_path, max_cards, None, None)