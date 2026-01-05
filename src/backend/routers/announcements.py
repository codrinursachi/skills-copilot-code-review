from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from datetime import datetime
from ..database import db
from ..routers.auth import get_current_user

router = APIRouter()

# MongoDB collection
announcements_collection = db['announcements']


def announcement_dict(doc):
    return {
        "id": str(doc.get("_id")),
        "message": doc.get("message"),
        "start_date": doc.get("start_date"),
        "expiration_date": doc.get("expiration_date"),
        "created_by": doc.get("created_by"),
    }

@router.get("/announcements", response_model=List[dict])
def get_announcements():
    now = datetime.utcnow().isoformat()
    docs = announcements_collection.find({
        "$or": [
            {"expiration_date": {"$gte": now}},
            {"expiration_date": None}
        ]
    })
    return [announcement_dict(doc) for doc in docs]

@router.post("/announcements", response_model=dict)
def create_announcement(message: str, expiration_date: str, start_date: Optional[str] = None, user=Depends(get_current_user)):
    if not message or not expiration_date:
        raise HTTPException(status_code=400, detail="Message and expiration date required.")
    doc = {
        "message": message,
        "start_date": start_date,
        "expiration_date": expiration_date,
        "created_by": user["username"]
    }
    result = announcements_collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return announcement_dict(doc)

@router.put("/announcements/{announcement_id}", response_model=dict)
def update_announcement(announcement_id: str, message: Optional[str] = None, expiration_date: Optional[str] = None, start_date: Optional[str] = None, user=Depends(get_current_user)):
    doc = announcements_collection.find_one({"_id": announcement_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Announcement not found.")
    update = {}
    if message is not None:
        update["message"] = message
    if expiration_date is not None:
        update["expiration_date"] = expiration_date
    if start_date is not None:
        update["start_date"] = start_date
    if update:
        announcements_collection.update_one({"_id": announcement_id}, {"$set": update})
    return announcement_dict(announcements_collection.find_one({"_id": announcement_id}))

@router.delete("/announcements/{announcement_id}")
def delete_announcement(announcement_id: str, user=Depends(get_current_user)):
    doc = announcements_collection.find_one({"_id": announcement_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Announcement not found.")
    announcements_collection.delete_one({"_id": announcement_id})
    return {"success": True}
