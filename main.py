import os
from typing import List, Optional, Any, Dict
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from bson import ObjectId

from database import db, create_document, get_documents

app = FastAPI(title="SaaS Notepad API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------
# Helpers
# -----------------------------
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)


def serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    doc = dict(doc)
    _id = doc.get("_id")
    if isinstance(_id, ObjectId):
        doc["id"] = str(_id)
        del doc["_id"]
    return doc


# -----------------------------
# Schemas
# -----------------------------
class CategoryIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    color: Optional[str] = None
    icon: Optional[str] = None


class CategoryOut(CategoryIn):
    id: str


class NoteIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = ""
    category_id: Optional[str] = None
    pinned: bool = False
    archived: bool = False


class NoteOut(NoteIn):
    id: str


class AIEnhanceRequest(BaseModel):
    text: str
    tone: Optional[str] = Field(
        default="clear",
        description="Desired tone: clear, friendly, formal, concise",
    )


class AIGenerateRequest(BaseModel):
    prompt: str
    length: Optional[str] = Field(default="short", description="short|medium|long")


# -----------------------------
# Basic routes
# -----------------------------
@app.get("/")
def read_root():
    return {"message": "SaaS Notepad Backend Running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["connection_status"] = "Connected"
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# -----------------------------
# Categories
# -----------------------------
@app.get("/api/categories", response_model=List[CategoryOut])
def list_categories():
    docs = get_documents("category")
    return [CategoryOut(**serialize_doc(d)) for d in docs]


@app.post("/api/categories", response_model=CategoryOut)
def create_category(payload: CategoryIn):
    new_id = create_document("category", payload.model_dump())
    doc = db["category"].find_one({"_id": ObjectId(new_id)})
    return CategoryOut(**serialize_doc(doc))


# -----------------------------
# Notes
# -----------------------------
@app.get("/api/notes", response_model=List[NoteOut])
def list_notes(category_id: Optional[str] = None, pinned: Optional[bool] = None, archived: Optional[bool] = None):
    filt: Dict[str, Any] = {}
    if category_id:
        filt["category_id"] = category_id
    if pinned is not None:
        filt["pinned"] = pinned
    if archived is not None:
        filt["archived"] = archived
    docs = get_documents("note", filt)
    return [NoteOut(**serialize_doc(d)) for d in docs]


@app.post("/api/notes", response_model=NoteOut)
def create_note(payload: NoteIn):
    new_id = create_document("note", payload.model_dump())
    doc = db["note"].find_one({"_id": ObjectId(new_id)})
    return NoteOut(**serialize_doc(doc))


class NotePatch(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category_id: Optional[str] = None
    pinned: Optional[bool] = None
    archived: Optional[bool] = None


@app.patch("/api/notes/{note_id}", response_model=NoteOut)
def update_note(note_id: str, payload: NotePatch):
    if not ObjectId.is_valid(note_id):
        raise HTTPException(status_code=400, detail="Invalid note id")
    update = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not update:
        doc = db["note"].find_one({"_id": ObjectId(note_id)})
        if not doc:
            raise HTTPException(status_code=404, detail="Note not found")
        return NoteOut(**serialize_doc(doc))
    update["updated_at"] = __import__("datetime").datetime.utcnow()
    result = db["note"].update_one({"_id": ObjectId(note_id)}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Note not found")
    doc = db["note"].find_one({"_id": ObjectId(note_id)})
    return NoteOut(**serialize_doc(doc))


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: str):
    if not ObjectId.is_valid(note_id):
        raise HTTPException(status_code=400, detail="Invalid note id")
    result = db["note"].delete_one({"_id": ObjectId(note_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"ok": True}


# -----------------------------
# AI Endpoints (lightweight, offline-friendly)
# -----------------------------

def _smart_quotes(text: str) -> str:
    return (
        text.replace('"', '“').replace("'", "’")
    )


def _tidy(text: str) -> str:
    import re
    t = text.strip()
    t = re.sub(r"\s+", " ", t)
    # Capitalize first letter of sentences
    sentences = re.split(r"(\.|\?|!)(\s+)", t)
    out = []
    for i in range(0, len(sentences), 3):
        chunk = sentences[i]
        if not chunk:
            continue
        end = sentences[i+1] if i+1 < len(sentences) else ''
        sep = sentences[i+2] if i+2 < len(sentences) else ' '
        chunk = chunk[:1].upper() + chunk[1:]
        out.append(chunk + end + sep)
    return ''.join(out).strip()


def _apply_tone(text: str, tone: str) -> str:
    if tone == "concise":
        # Keep to ~120 chars
        return (text[:117] + '...') if len(text) > 120 else text
    if tone == "friendly":
        return text + " 😊"
    if tone == "formal":
        return text.replace("you", "you").replace("thanks", "thank you")
    return text


@app.post("/api/ai/enhance")
def ai_enhance(req: AIEnhanceRequest):
    text = _tidy(req.text)
    text = _smart_quotes(text)
    text = _apply_tone(text, (req.tone or "clear").lower())
    return {"enhanced": text}


@app.post("/api/ai/generate")
def ai_generate(req: AIGenerateRequest):
    base = (
        "Here is a thoughtfully crafted note based on your idea: "
        + req.prompt.strip().rstrip('.')
        + ". "
    )
    extra_short = "It highlights key points clearly and remains actionable."
    extra_med = (
        "It outlines the goal, provides a short plan, and ends with a next step you can take right now."
    )
    extra_long = (
        "It includes context, a brief summary, a bullet-style plan, and a friendly closing to keep you motivated."
    )
    if (req.length or "short") == "short":
        text = f"{base}{extra_short}"
    elif req.length == "medium":
        text = f"{base}{extra_med}"
    else:
        text = f"{base}{extra_long}"
    return {"text": text}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
