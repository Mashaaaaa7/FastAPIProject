import re
import unicodedata
from typing import List, Dict, Optional, Tuple
import pdfplumber
import torch
from sqlalchemy.orm import Session
from app import models


class QAGenerator:
    """
    Извлекаем:
    - Подлежащее (кто)
    - Глагол/предикат (что делал)
    - Дополнение (кого/что)
   """

    def __init__(self, use_gpt: bool = False):
        self.device = 0 if torch.cuda.is_available() else -1
        print("✅ QAGenerator инициализирован!", flush=True)

    def clean_text(self, text: str) -> str:
        """Очищает текст"""
        if not text:
            return ""
        text = ''.join(ch for ch in text if unicodedata.category(ch)[0] != 'C' or ch in '\n\t')
        text = re.sub(r'[>~<•»«„"\[\]{}()_\-–—]+', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _clean_paragraph(self, text: str) -> str:
        """Очищает абзац"""
        text = re.sub(r'\*\*', '', text)
        text = re.sub(r'^\s*[\*\-\•]\s*', '', text)
        text = re.sub(r'^\s*\d+[\.\s]\s*', '', text)
        text = re.sub(r'^\s*[;:]\s*', '', text)
        text = self.clean_text(text)
        return text

    def extract_meaningful_text(self, file_path: str) -> List[Dict]:
        """Извлекает абзацы из PDF"""
        chunks = []

        try:
            with pdfplumber.open(file_path) as pdf:
                print(f"📄 PDF имеет {len(pdf.pages)} страниц", flush=True)

                for page_num, page in enumerate(pdf.pages):
                    raw_text = page.extract_text()
                    if not raw_text:
                        continue

                    paragraphs = raw_text.split('\n\n')

                    for para in paragraphs:
                        cleaned = self._clean_paragraph(para)

                        if len(cleaned) < 50:
                            continue

                        if any(bad in cleaned.lower()
                               for bad in ['ipynb', 'colab', 'http', '©', '®']):
                            continue

                        chunks.append({
                            "text": cleaned,
                            "page": page_num,
                            "word_count": len(cleaned.split())
                        })

            print(f"📊 Найдено {len(chunks)} абзацев", flush=True)
            return chunks
        except Exception as e:
            print(f"❌ Ошибка: {e}", flush=True)
            return []

    def _split_into_sentences(self, text: str) -> List[str]:
        """Разбиение на предложения"""
        text = text.replace('Др.', 'Др_').replace('др.', 'др_').replace('т.е.', 'т_е')
        sentences = re.split(r'([.!?]+)\s+(?=[А-ЯёЁ])', text)

        result = []
        for i in range(0, len(sentences) - 1, 2):
            if i + 1 < len(sentences):
                sentence = sentences[i] + sentences[i + 1]
                sentence = sentence.replace('Др_', 'Др.').replace('др_', 'др.').replace('т_е', 'т.е')
                sentence = sentence.strip()
                if len(sentence) > 15:
                    result.append(sentence)

        if sentences and len(sentences[-1]) > 15:
            last = sentences[-1].replace('Др_', 'Др.').replace('др_', 'др.').replace('т_е', 'т.е').strip()
            if last and not last.endswith(('.', '!', '?')):
                last += '.'
            if len(last) > 15:
                result.append(last)

        return result

    def _extract_parts(self, sentence: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        извлекает части предложения:
        - subject (подлежащее)
        - verb (глагол/предикат)
        - obj (дополнение)

        Примеры:
        "Нацисты стремились к территориальной экспансии"
        → subject="Нацисты", verb="стремились", obj="территориальной экспансии"

        "СССР поддерживал республиканское правительство Испании"
        → subject="СССР", verb="поддерживал", obj="республиканское правительство Испании"
        """
        sent = sentence.rstrip('.!?')
        sent_lower = sent.lower()
        words = sent.split()

        subject = None
        verb = None
        obj = None

        # Ищем глагол
        verbs = [
            'привел', 'привела', 'привело', 'привели',
            'стремился', 'стремилась', 'стремились',
            'поддержива', 'поддерж', 'помог',
            'начал', 'началась', 'началось', 'началось',
            'вызвал', 'вызвала', 'вызвало', 'вызвали',
            'выдвинул', 'выдвинула',
            'создал', 'создала', 'создало', 'создали',
            'демонстрирова',
            'стал', 'стала', 'стало',
            'показыва', 'показал',
            'играл', 'играла', 'играло',
            'боролся', 'боролась',
            'участвовал', 'участвовала',
            'провел', 'провела', 'проводи',
            'предпринял', 'предприняла',
            'совершил', 'совершила'
        ]

        verb_idx = -1
        for i, word in enumerate(words):
            w_lower = word.lower()
            if any(v in w_lower for v in verbs):
                verb = word.rstrip('.,;:')
                verb_idx = i
                break

        if verb_idx >= 0:
            # Подлежащее - обычно первое существительное перед глаголом
            skip = {'в', 'на', 'по', 'из', 'к', 'при', 'от', 'под', 'над', 'с', 'о', 'об', 'и', 'или', 'но'}
            for i in range(verb_idx):
                w = words[i].lower()
                if w not in skip and len(w) > 2:
                    subject = words[i].rstrip('.,;:')
                    break

            # Дополнение - всё после глагола до точки
            if verb_idx + 1 < len(words):
                obj_words = []
                for i in range(verb_idx + 1, len(words)):
                    obj_words.append(words[i].rstrip('.,;:'))
                if obj_words:
                    obj = ' '.join(obj_words)

        return subject, verb, obj

    def _generate_question_from_parts(self, subject: str, verb: str, obj: str, sentence: str) -> Optional[str]:
        """
        генерирует вопрос на основе частей
        """
        verb_lower = verb.lower() if verb else ""

        # Правило 1: глагол "привел/привела" → "К чему привел X?"
        if 'привел' in verb_lower:
            if subject:
                return f"К чему привел {subject}?"
            return "К чему это привело?"

        # Правило 2: глагол "стремился" → "К чему стремился X?"
        if 'стремил' in verb_lower:
            if subject:
                return f"К чему стремился {subject}?"
            if obj:
                return f"К чему стремились?"
            return "К чему стремились?"

        # Правило 3: глагол "поддерживал" → "Кого поддерживал X?"
        if 'поддерж' in verb_lower or 'помог' in verb_lower:
            if subject:
                return f"Кого поддерживал {subject}?"
            return "Кого поддерживали?"

        # Правило 4: глагол "вызвал" → "Что вызвал X?"
        if 'вызва' in verb_lower:
            if obj:
                return f"Что вызвал {subject or 'этот'} конфликт?"
            return "Что произошло в результате?"

        # Правило 5: глагол "выдвинул" → "Какие требования выдвинул X?"
        if 'выдвину' in verb_lower:
            if subject:
                return f"Какие требования выдвинул {subject}?"
            return "Какие требования были выдвинуты?"

        # Правило 6: глагол "создал" → "Что создал X?"
        if 'создал' in verb_lower or 'формирова' in verb_lower:
            if obj:
                return f"Что создал {subject or 'он'}?"
            return "Что было создано?"

        # Правило 7: глагол "демонстрирова" → "Что демонстрировал X?"
        if 'демонстр' in verb_lower or 'показыва' in verb_lower:
            if subject:
                return f"Что демонстрировал {subject}?"
            if obj:
                return f"Что это показывало?"
            return "Что это демонстрировало?"

        # Правило 8: глагол "стал" → "Чем стал X?"
        if verb_lower.startswith('стал') or verb_lower.startswith('стала') or verb_lower.startswith('стало'):
            if obj:
                return f"Чем стал {subject}?"
            return "Чем это стало?"

        # Правило 9: глагол "играл" → "Какую роль играл X?"
        if 'играл' in verb_lower:
            if subject:
                return f"Какую роль играл {subject}?"
            return "Какую роль это играло?"

        # Правило 10: глагол "провел" → "Что провел X?"
        if 'провел' in verb_lower or 'провожде' in verb_lower:
            if subject:
                return f"Что провел {subject}?"
            if obj:
                return f"Какую операцию провели?"
            return "Что было проведено?"

        # Правило 11: глагол "участвовал" → "Где участвовал X?"
        if 'участвова' in verb_lower:
            if subject:
                return f"Где участвовал {subject}?"
            return "Где это происходило?"

        # Fallback
        if subject and obj:
            return f"Какова была роль {subject} в {obj}?"
        if subject:
            return f"Что произошло с {subject}?"

        return None

    def generate_qa_pair_from_sentence(self, sentence: str) -> Optional[Dict]:
        """Генерирует Q&A пару из одного предложения"""
        try:
            if len(sentence) < 20:
                return None

            # ✅ Извлекаем части предложения
            subject, verb, obj = self._extract_parts(sentence)

            # Если нет глагола - пропускаем
            if not verb:
                return None

            # ✅ Генерируем конкретный вопрос
            question = self._generate_question_from_parts(subject or "", verb, obj or "", sentence)

            if not question:
                return None

            if not question.endswith('?'):
                question += '?'

            if len(question) < 5 or len(question) > 200:
                return None

            if not re.search(r'[а-яА-ЯёЁ]', question):
                return None

            answer = sentence.strip()

            if len(answer) < 20:
                return None

            return {
                "question": question,
                "answer": answer,
                "context": sentence[:100]
            }

        except Exception as e:
            print(f"⚠️ Ошибка: {e}", flush=True)
            return None

    def process_pdf_with_cancellation(self, file_path: str, max_cards: int, db: Session, status_id: int) -> List[Dict]:
        """Обрабатывает PDF"""
        print(f"\n🔄 Начинаю обработку {file_path}...", flush=True)
        print(f"🎯 Максимум: {max_cards} карточек", flush=True)

        paragraphs = self.extract_meaningful_text(file_path)

        if not paragraphs:
            print("❌ Не найдено абзацев!", flush=True)
            return []

        flashcards = []
        seen_questions = set()

        for p_idx, para_dict in enumerate(paragraphs):
            if len(flashcards) >= max_cards:
                break

            para_text = para_dict["text"]
            sentences = self._split_into_sentences(para_text)

            print(f"\n📖 Абзац {p_idx + 1}: {len(sentences)} предложений")

            for sentence in sentences:
                if len(flashcards) >= max_cards:
                    break

                if db is not None:
                    try:
                        status = db.query(models.ProcessingStatus).filter(
                            models.ProcessingStatus.id == status_id
                        ).first()

                        if status and status.should_cancel:
                            print(f"⛔ Обработка отменена", flush=True)
                            return flashcards[:max_cards]
                    except:
                        pass

                qa_pair = self.generate_qa_pair_from_sentence(sentence)

                if qa_pair:
                    question = qa_pair["question"]

                    if question not in seen_questions:
                        seen_questions.add(question)
                        flashcards.append({
                            "question": question,
                            "answer": qa_pair["answer"],
                            "context": qa_pair["context"],
                            "source": ""
                        })
                        print(f"  ✅ [{len(flashcards)}/{max_cards}] {question}", flush=True)

                        if len(flashcards) >= max_cards:
                            break

        print(f"\n✅ Итого: {len(flashcards)} карточек (лимит: {max_cards})", flush=True)
        return flashcards[:max_cards]

    def process_pdf(self, file_path: str, max_cards: int = 10) -> List[Dict]:
        """Обрабатывает PDF"""
        return self.process_pdf_with_cancellation(file_path, max_cards, None, None)