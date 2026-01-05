from fastapi import APIRouter, HTTPException, Depends, Request, status, Body
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, validator
from bson import ObjectId
from bson.errors import InvalidId
from ..database import db

router = APIRouter()

# MongoDB collection
announcements_collection = db['announcements']


def get_current_user(request: Request) -> dict:
    """
    Dependency that retrieves the current authenticated user from the request.

    This implementation expects the username to be provided via the `X-User-Name`
    HTTP header. If the header is missing, a 401 Unauthorized error is raised.
    """
    username = request.headers.get("X-User-Name")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated: missing X-User-Name header.",
        )
    return {"username": username}


class AnnouncementCreate(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    start_date: Optional[str] = None
    expiration_date: str

    @validator('message')
    def validate_message(cls, v):
        if not v or not v.strip():
            raise ValueError('Message cannot be empty')
        return v.strip()

    @validator('expiration_date')
    def validate_expiration_date(cls, v):
        if not v:
            raise ValueError('Expiration date is required')
        try:
            exp_date = datetime.fromisoformat(v.replace('Z', '+00:00'))
            if exp_date <= datetime.utcnow():
                raise ValueError('Expiration date must be in the future')
        except (ValueError, TypeError) as e:
            if 'must be in the future' in str(e):
                raise e
            raise ValueError('Invalid expiration date format')
        return v

    @validator('start_date')
    def validate_start_date(cls, v, values):
        if v:
            try:
                start = datetime.fromisoformat(v.replace('Z', '+00:00'))
                if 'expiration_date' in values and values['expiration_date']:
                    exp = datetime.fromisoformat(values['expiration_date'].replace('Z', '+00:00'))
                    if start >= exp:
                        raise ValueError('Start date must be before expiration date')
            except (ValueError, TypeError) as e:
                if 'must be before' in str(e):
                    raise e
                raise ValueError('Invalid start date format')
        return v


class AnnouncementUpdate(BaseModel):
    message: Optional[str] = Field(None, min_length=1, max_length=5000)
    start_date: Optional[str] = None
    expiration_date: Optional[str] = None

    @validator('message')
    def validate_message(cls, v):
        if v is not None:
            if not isinstance(v, str):
                raise ValueError('Message must be a string')
            if not v or not v.strip():
                raise ValueError('Message cannot be empty')
            return v.strip()
        return v

    @validator('expiration_date')
    def validate_expiration_date(cls, v):
        if v is not None and v.strip():
            try:
                exp_date = datetime.fromisoformat(v.replace('Z', '+00:00'))
                if exp_date <= datetime.utcnow():
                    raise ValueError('Expiration date must be in the future')
            except (ValueError, TypeError) as e:
                if 'must be in the future' in str(e):
                    raise e
                raise ValueError('Invalid expiration date format')
            return v
        return None

    @validator('start_date')
    def validate_start_date(cls, v):
        # Convert empty strings to None
        if v is not None:
            if not isinstance(v, str):
                raise ValueError('Start date must be a string')
            if not v.strip():
                return None
            try:
                # Just validate format, cross-validation with expiration_date happens in endpoint
                datetime.fromisoformat(v.replace('Z', '+00:00'))
            except (ValueError, TypeError):
                raise ValueError('Invalid start date format')
        return v


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
def create_announcement(announcement: AnnouncementCreate = Body(...), user=Depends(get_current_user)):
    doc = {
        "message": announcement.message,
        "start_date": announcement.start_date,
        "expiration_date": announcement.expiration_date,
        "created_by": user["username"]
    }
    result = announcements_collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return announcement_dict(doc)


@router.put("/announcements/{announcement_id}", response_model=dict)
def update_announcement(announcement_id: str, announcement: AnnouncementUpdate = Body(...), user=Depends(get_current_user)):
    # Convert string ID to ObjectId
    try:
        obj_id = ObjectId(announcement_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid announcement ID format.")
    
    doc = announcements_collection.find_one({"_id": obj_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Announcement not found.")
    
    # Check authorization - only creator can update
    if doc.get("created_by") != user["username"]:
        raise HTTPException(status_code=403, detail="You are not authorized to update this announcement.")
    
    update = {}
    if announcement.message is not None:
        update["message"] = announcement.message
    if announcement.expiration_date is not None:
        update["expiration_date"] = announcement.expiration_date
    if announcement.start_date is not None:
        update["start_date"] = announcement.start_date
    
    if not update:
        # No changes needed, return existing document
        return announcement_dict(doc)
    
    # Validate date logic with existing values
    final_start = update.get("start_date", doc.get("start_date"))
    final_expiration = update.get("expiration_date", doc.get("expiration_date"))
    
    if final_start and final_expiration:
        try:
            start_dt = datetime.fromisoformat(final_start.replace('Z', '+00:00'))
            exp_dt = datetime.fromisoformat(final_expiration.replace('Z', '+00:00'))
            if start_dt >= exp_dt:
                raise HTTPException(status_code=400, detail="Start date must be before expiration date.")
        except ValueError as e:
            if "must be before" not in str(e):
                raise HTTPException(status_code=400, detail="Invalid date format.")
            raise
    
    announcements_collection.update_one({"_id": obj_id}, {"$set": update})
    updated_doc = announcements_collection.find_one({"_id": obj_id})
    return announcement_dict(updated_doc)


@router.delete("/announcements/{announcement_id}")
def delete_announcement(announcement_id: str, user=Depends(get_current_user)):
    # Convert string ID to ObjectId
    try:
        obj_id = ObjectId(announcement_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid announcement ID format.")
    
    doc = announcements_collection.find_one({"_id": obj_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Announcement not found.")
    
    # Check authorization - only creator can delete
    if doc.get("created_by") != user["username"]:
        raise HTTPException(status_code=403, detail="You are not authorized to delete this announcement.")
    
    announcements_collection.delete_one({"_id": obj_id})
    return {"success": True}
