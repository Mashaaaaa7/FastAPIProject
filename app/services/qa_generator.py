from transformers import pipeline
import pdfplumber
import re
import unicodedata
from typing import List, Dict
import torch


class QAGenerator:
    def __init__(self, use_ollama: bool = False):
        self.device = 0 if torch.cuda.is_available() else -1
        self.use_ollama = use_ollama

        if use_ollama:
            print("⏳ Используем Ollama...")
            self.ollama_url = "http://localhost:11434/api/generate"
        else:
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

    def extract_key_entities(self, text: str) -> List[str]:
        """Извлекает ключевые сущности"""
        words = text.split()
        entities = []

        for word in words:
            clean_word = re.sub(r'[,.!?;:]+$', '', word)

            if (len(clean_word) > 4 and
                    clean_word[0].isupper() and
                    clean_word not in ['В', 'По', 'От', 'На', 'С', 'И', 'Что']):
                entities.append(clean_word)

        return list(set(entities))[:5]

    def extract_summary(self, text: str) -> str:
        """Извлекает суть текста"""
        sentences = re.split(r'[.!?]+', text)
        long_sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

        if long_sentences:
            return self.clean_text(long_sentences[0])
        return self.clean_text(text[:150])

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

                    # Удаляем шумные префиксы (даты, номера, технические данные)
                    text = re.sub(r'^\d{2}\.\d{2}\.\d{4}.*?Colab\s*', '', text)
                    text = re.sub(r'https?://[^\s]+', '', text)
                    text = re.sub(r'\d{4}.*?ipynb.*?Colab', '', text, flags=re.IGNORECASE)

                    paragraphs = [p.strip() for p in text.split('\n') if len(p.strip()) > 50]

                    for para in paragraphs:
                        # Разбиваем на СМЫСЛОВЫЕ куски (не просто по точкам)
                        chunks_from_para = self._split_into_chunks(para)
                        chunks.extend(chunks_from_para)

            # Фильтруем откровенный мусор
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

        # Разбиваем по точкам, но сохраняем длину
        sentences = re.split(r'[.!?]+\s+', text)

        # Объединяем короткие предложения в одно
        combined = []
        current = ""

        for sent in sentences:
            sent = sent.strip()
            if not sent or len(sent) < 5:
                continue

            current += sent + ". "

            # Если накопилось достаточно — сохраняем
            if len(current.split()) >= 12:  # Минимум 12 слов
                combined.append(current.strip())
                current = ""

        if current.strip():
            combined.append(current.strip())

        # Преобразуем в chunks
        for i, chunk_text in enumerate(combined):
            if len(chunk_text) > 50:  # Минимум 50 символов
                chunks.append({
                    "text": chunk_text,
                    "page": 0,  # Не важно для нас
                    "word_count": len(chunk_text.split())
                })

        return chunks

    def generate_qa_pair_rut5(self, context: str) -> Dict:
        """Генерирует реальные QA пары"""
        try:
            context_clean = self.clean_text(context[:500])

            # Удаляем цифры и шум
            context_clean = re.sub(r'\b\d{1,3}\b', '', context_clean)
            context_clean = re.sub(r'\s+', ' ', context_clean).strip()

            if len(context_clean) < 60:
                return None

            # Разбиваем на предложения
            sentences = [s.strip() for s in re.split(r'[.!?]+', context_clean)]
            long_sentences = [s for s in sentences if len(s.split()) >= 8]

            if not long_sentences:
                return None

            sentence = long_sentences[0]
            words = [w for w in sentence.split() if len(w) > 3]

            if len(words) < 5:
                return None

            # Ищем РЕАЛЬНОЕ ключевое слово (существительное)
            important_words = [
                w.lower() for w in words
                if w[0].isupper() and w.lower() not in
                   ['где', 'когда', 'какой', 'какая', 'какие', 'это', 'эта']
            ]

            if not important_words:
                return None

            key_term = important_words[0]
            question = f"Объясните, что такое {key_term}?"
            answer = sentence

            if (len(question) > 15 and
                    len(answer) > 50 and
                    key_term in answer.lower()):
                return {
                    "question": question,
                    "answer": answer,
                    "context": context_clean[:150]
                }

            return None
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
            return None

    def create_quality_fallback(self, context: str) -> Dict:
        """Fallback — берём целое предложение как есть"""
        try:
            context_clean = self.clean_text(context[:500])

            # Ищем хорошее предложение
            sentences = [s.strip() for s in re.split(r'[.!?]+', context_clean)
                         if len(s.strip()) > 50]

            if not sentences:
                return None

            sentence = sentences[0]
            words = sentence.split()

            if len(words) < 7:
                return None

            # Берём первое-второе слово как тему
            topic = ' '.join(words[:2]).lower()

            question = f"Объясните, что произойдёт, если {topic}?"
            answer = sentence

            if len(answer) > 40:
                return {
                    "question": question,
                    "answer": answer,
                    "context": context_clean[:120]
                }

            return None
        except:
            return None

    def process_pdf(self, file_path: str, max_cards: int = 10) -> List[Dict]:
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

            qa_pair = self.generate_qa_pair_rut5(chunk['text'])

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
            else:
                fallback_qa = self.create_quality_fallback(chunk['text'])
                flashcard = {
                    "id": len(flashcards) + 1,
                    "question": fallback_qa["question"],
                    "answer": fallback_qa["answer"],
                    "context": fallback_qa["context"],
                    "source": f"Page {chunk['page']}"
                }
                flashcards.append(flashcard)
                print(f"  🔄 [{len(flashcards)}] {fallback_qa['question'][:60]}...")

        print(f"✅ Создано {len(flashcards)} карточек")
        return flashcards