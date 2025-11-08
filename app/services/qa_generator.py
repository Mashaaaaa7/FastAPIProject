from transformers import pipeline
import pdfplumber
import re
import unicodedata
from typing import List, Dict
import torch
import random
import requests


class QAGenerator:
    def __init__(self, use_ollama: bool = False):
        self.device = 0 if torch.cuda.is_available() else -1
        self.use_ollama = use_ollama

        if use_ollama:
            print("⏳ Используем Ollama для генерации контента...")
            self.ollama_url = "http://localhost:11434/api/generate"
        else:
            print("⏳ Загружаю русскую модель для генерации контента...")

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
        """Извлекает осмысленные фрагменты текста"""
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

                    paragraphs = [p.strip() for p in text.split('\n\n') if len(p.strip()) > 50]

                    for para in paragraphs:
                        sentences = re.split(r'[.!?]+\s+', para)

                        for sent in sentences:
                            sent = self.clean_text(sent)
                            words = sent.split()

                            if (8 <= len(words) <= 50 and
                                    len(sent) > 40 and
                                    sum(1 for c in sent if c.isalpha()) / len(sent) > 0.7):
                                chunks.append({
                                    "text": sent,
                                    "page": i + 1,
                                    "word_count": len(words)
                                })

            print(f"📊 Найдено {len(chunks)} содержательных фрагментов")
            return chunks

        except Exception as e:
            print(f"❌ Ошибка при извлечении текста: {e}")
            return []

    def generate_qa_pair_ollama(self, context: str) -> Dict:
        """Генерирует QA пару через Ollama"""
        try:
            prompt = f"""На основе этого текста создай вопрос и ответ на русском:

Текст: {context[:400]}

Формат ответа (точно):
ВОПРОС: [вопрос на русском]
ОТВЕТ: [ответ на русском]"""

            response = requests.post(
                self.ollama_url,
                json={"model": "llama2", "prompt": prompt, "stream": False}
            )

            if response.status_code != 200:
                return None

            generated = response.json()['response']

            question_match = re.search(r'ВОПРОС:\s*(.*?)(?=\s*ОТВЕТ:|$)', generated, re.DOTALL)
            answer_match = re.search(r'ОТВЕТ:\s*(.*?)$', generated, re.DOTALL)

            if question_match and answer_match:
                question = self.clean_text(question_match.group(1).strip())
                answer = self.clean_text(answer_match.group(1).strip())

                if len(question) > 15 and len(answer) > 20 and '?' in question:
                    return {
                        "question": question,
                        "answer": answer,
                        "context": context[:200] + "..." if len(context) > 200 else context
                    }
            return None

        except Exception as e:
            print(f"⚠️ Ошибка Ollama: {e}")
            return None

    def generate_qa_pair_rut5(self, context: str) -> Dict:
        """Генерирует QA пару через RuT5"""
        try:
            context_clean = self.clean_text(context[:400])

            if len(context_clean) < 30:
                return None

            prompt = f"вопрос-ответ: {context_clean}"

            result = self.generator(
                prompt,
                max_new_tokens=80,
                num_beams=2
            )

            generated = self.clean_text(result[0]['generated_text'])

            parts = generated.split(' | ')
            if len(parts) >= 2:
                question = self.clean_text(parts[0])
                answer = self.clean_text(parts[1])

                if not question.endswith('?'):
                    question += '?'

                if len(question) > 15 and len(answer) > 20:
                    return {
                        "question": question,
                        "answer": answer,
                        "context": context_clean[:200] + "..." if len(context_clean) > 200 else context_clean
                    }
            return None

        except Exception as e:
            print(f"⚠️ Ошибка RuT5: {e}")
            return None

    def create_fallback_qa(self, context: str) -> Dict:
        """Создает резервную QA пару"""
        words = context.split()
        key_terms = [word for word in words if len(word) > 4 and word[0].isupper()]

        if key_terms:
            term = random.choice(key_terms[:3]) if key_terms else "понятие"
            question = f"Что означает '{term}' в контексте этого текста?"
            answer = f"{term} в данном контексте означает: {context[:180]}..."
        else:
            question = "Какую основную информацию содержит этот текст?"
            answer = f"Основное содержание: {context[:200]}..."

        return {
            "question": question,
            "answer": answer,
            "context": context[:150] + "..." if len(context) > 150 else context
        }

    def process_pdf(self, file_path: str, max_cards: int = 10) -> List[Dict]:
        print(f"\n🔄 Начинаю обработку {file_path}...")
        print(f"🎯 Цель: {max_cards} карточек")

        chunks = self.extract_meaningful_text(file_path)

        if not chunks:
            print("❌ Не найдено подходящих текстовых фрагментов!")
            return []

        print(f"✅ Найдено {len(chunks)} содержательных фрагментов")

        chunks.sort(key=lambda x: abs(x['word_count'] - 20))

        flashcards = []

        for chunk in chunks[:max_cards * 2]:
            if len(flashcards) >= max_cards:
                break

            if self.use_ollama:
                qa_pair = self.generate_qa_pair_ollama(chunk['text'])
            else:
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
                print(f"  ✅ [{len(flashcards)}] Q: {qa_pair['question'][:70]}...")
            else:
                fallback_qa = self.create_fallback_qa(chunk['text'])
                flashcard = {
                    "id": len(flashcards) + 1,
                    "question": fallback_qa["question"],
                    "answer": fallback_qa["answer"],
                    "context": fallback_qa["context"],
                    "source": f"Page {chunk['page']}"
                }
                flashcards.append(flashcard)
                print(f"  🔄 [{len(flashcards)}] Fallback: {fallback_qa['question'][:70]}...")

        print(f"✅ Создано {len(flashcards)} карточек")
        return flashcards
