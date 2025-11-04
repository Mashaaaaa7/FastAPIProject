from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class PDFFileBase(BaseModel):
    filename: str
    file_size: int

class PDFFileCreate(PDFFileBase):
    file_path: str
    user_id: int

class PDFFile(PDFFileBase):
    id: int
    created_at: datetime
    user_id: int
    is_deleted: bool

    class Config:
        from_attributes = True

class ActionHistoryBase(BaseModel):
    action: str
    details: str

class ActionHistoryCreate(ActionHistoryBase):
    deck_name: Optional[str] = None
    filename: Optional[str] = None
    user_id: int

class ActionHistory(ActionHistoryBase):
    id: int
    deck_name: Optional[str]
    filename: Optional[str]
    timestamp: datetime
    user_id: int

    class Config:
        from_attributes = True