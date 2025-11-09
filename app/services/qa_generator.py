from transformers import pipeline
import pdfplumber
import re
import unicodedata
from typing import List, Dict
import torch


class QAGenerator:
    def __init__(self):
        self.device = 0 if torch.cuda.is_available() else -1
        print("⏳ Загружаю русскую модель...")
        self.generator = pipeline(
            "text2text-generation",
            model="cointegrated/rut5-base-multitask",
            device=self.device,
            torch_dtype=torch.float32
        )
        print("✅ Модель загружена!")

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

    def _extract_key_phrase(self, text: str) -> str:
        """Извлекает главное существительное из текста"""
        words = text.split()

        # Стоп-слова и прилагательные
        bad_words = {
            'это', 'для', 'при', 'как', 'что', 'в', 'по', 'на', 'с', 'и', 'или', 'то',
            'был', 'была', 'были', 'быть', 'являются', 'является', 'есть',
            'если', 'здесь', 'наконец', 'однако', 'рассматривая', 'выделение',
            'предисловие', 'обучение', 'набор'
        }

        idx = 0
        while idx < len(words) and words[idx].lower() in bad_words:
            idx += 1

        working_words = words[idx:]

        # Ищем существительное (слово с заглавной буквы, длина > 5)
        for w in working_words[:10]:
            w_lower = w.lower().rstrip(',:;.')
            if len(w_lower) > 5 and w[0].isupper() and w_lower not in bad_words:
                return w_lower

        # Fallback
        return "концепция"

    def _generate_question(self, text: str) -> str:
        """Генерирует УМНЫЙ вопрос на основе анализа текста"""
        text_lower = text.lower()
        key_phrase = self._extract_key_phrase(text)

        # Анализируем содержание и генерируем подходящий вопрос

        if any(word in text_lower for word in ['представить', 'вводит', 'рассмотрены']):
            return f"Что представляет собой {key_phrase}?"

        elif any(word in text_lower for word in ['обучения', 'алгоритм', 'методы', 'подход']):
            return f"Как работает {key_phrase}?"

        elif any(word in text_lower for word in ['применени', 'использова', 'применяет']):
            return f"Где применяется {key_phrase}?"

        elif any(word in text_lower for word in ['рассмотр', 'обсужда', 'анализир']):
            return f"Какие особенности имеет {key_phrase}?"

        elif any(word in text_lower for word in ['содержит', 'включает', 'состоит']):
            return f"Из чего состоит {key_phrase}?"

        elif any(word in text_lower for word in ['может', 'помогает', 'способствует']):
            return f"Какая функция у {key_phrase}?"

        elif any(word in text_lower for word in ['данные', 'информация', 'результаты']):
            return f"Как интерпретировать {key_phrase}?"

        elif any(word in text_lower for word in ['процесс', 'этапы', 'шаги']):
            return f"Какие этапы содержит процесс {key_phrase}?"

        else:
            return f"Объясните, что такое {key_phrase}?"

    def generate_qa_pair(self, context: str) -> Dict:
        """Генерирует качественную QA пару"""
        try:
            context_clean = self.clean_text(context[:700])
            context_clean = re.sub(r'\b\d{1,3}\b', '', context_clean)
            context_clean = re.sub(r'\s+', ' ', context_clean).strip()

            if len(context_clean) < 100:
                return None

            if any(word in context_clean.lower() for word in
                   ['код', 'import', 'def ', 'print(', 'function', 'class ']):
                return None

            # Выбираем лучшие предложения
            sentences = [s.strip() for s in re.split(r'[.!?]+', context_clean)]
            candidate_sents = [s for s in sentences if len(s.split()) >= 12 and len(s) > 90]

            if not candidate_sents:
                return None

            # Пропускаем вводные фразы
            answer = None
            for sent in candidate_sents:
                if not any(marker in sent.lower() for marker in
                           ['номер', 'тема', 'раздел', 'глава', 'таблица', 'рисунок']):
                    answer = sent
                    break

            if not answer:
                answer = candidate_sents[0]

            # Генерируем вопрос
            question = self._generate_question(answer)

            answer = re.sub(r'\s+', ' ', answer).strip()
            question = re.sub(r'\s+', ' ', question).strip()

            # Проверяем качество
            if (len(question) > 12 and len(answer) > 90 and
                    '?' in question and
                    len(question) < 120):
                return {
                    "question": question,
                    "answer": answer,
                    "context": context_clean[:150]
                }

            return None

        except Exception as e:
            print(f"⚠️ Ошибка генерации: {e}")
            return None

    def process_pdf(self, file_path: str, max_cards: int = 10) -> List[Dict]:
        """Обрабатывает PDF и генерирует карточки"""
        print(f"\n🔄 Начинаю обработку {file_path}...")
        print(f"🎯 Цель: {max_cards} карточек")

        chunks = self.extract_meaningful_text(file_path)

        if not chunks:
            print("❌ Не найдено подходящих текстовых фрагментов!")
            return []

        print(f"✅ Найдено {len(chunks)} содержательных фрагментов")

        chunks.sort(key=lambda x: abs(x['word_count'] - 25))
        flashcards = []

        for chunk in chunks[:max_cards * 2]:
            if len(flashcards) >= max_cards:
                break

            qa_pair = self.generate_qa_pair(chunk['text'])

            if qa_pair:
                flashcard = {
                    "id": len(flashcards) + 1,
                    "question": qa_pair["question"],
                    "answer": qa_pair["answer"],
                    "context": qa_pair["context"],
                    "source": f"Page {chunk['page']}"
                }
                flashcards.append(flashcard)
                print(f"  ✅ [{len(flashcards)}] {qa_pair['question'][:60]}...")

        print(f"✅ Создано {len(flashcards)} карточек")
        return flashcards
