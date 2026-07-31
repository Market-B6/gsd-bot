from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from datetime import datetime
from pydantic import BaseModel
from app.database import get_db
from app.models import User, Meal, GlucoseReading, InsulinDose

router = APIRouter()

# Schemas
class MealCreate(BaseModel):
    user_id: int
    description: str
    datetime: datetime

class MealResponse(BaseModel):
    id: int
    user_id: int
    description: str
    datetime: datetime

    class Config:
        from_attributes = True

class GlucoseCreate(BaseModel):
    user_id: int
    value: float
    type: str
    meal_id: int | None = None
    datetime: datetime

class GlucoseResponse(BaseModel):
    id: int
    user_id: int
    value: float
    type: str
    is_normal: bool
    datetime: datetime

    class Config:
        from_attributes = True

class InsulinCreate(BaseModel):
    user_id: int
    units: float
    type: str
    datetime: datetime

class InsulinResponse(BaseModel):
    id: int
    user_id: int
    units: float
    type: str
    datetime: datetime

    class Config:
        from_attributes = True

# Endpoints
@router.post("/meals", response_model=MealResponse)
async def create_meal(meal: MealCreate, db: AsyncSession = Depends(get_db)):
    db_meal = Meal(**meal.model_dump())
    db.add(db_meal)
    await db.flush()
    await db.refresh(db_meal)
    return db_meal

@router.get("/meals/{user_id}", response_model=List[MealResponse])
async def get_meals(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Meal).where(Meal.user_id == user_id).order_by(Meal.datetime.desc()))
    return result.scalars().all()

@router.post("/glucose", response_model=GlucoseResponse)
async def create_glucose(glucose: GlucoseCreate, db: AsyncSession = Depends(get_db)):
    db_glucose = GlucoseReading(**glucose.model_dump())
    db.add(db_glucose)
    await db.flush()
    await db.refresh(db_glucose)
    return db_glucose

@router.get("/glucose/{user_id}", response_model=List[GlucoseResponse])
async def get_glucose(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GlucoseReading).where(GlucoseReading.user_id == user_id).order_by(GlucoseReading.datetime.desc()))
    return result.scalars().all()

@router.post("/insulin", response_model=InsulinResponse)
async def create_insulin(insulin: InsulinCreate, db: AsyncSession = Depends(get_db)):
    db_insulin = InsulinDose(**insulin.model_dump())
    db.add(db_insulin)
    await db.flush()
    await db.refresh(db_insulin)
    return db_insulin

@router.get("/insulin/{user_id}", response_model=List[InsulinResponse])
async def get_insulin(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(InsulinDose).where(InsulinDose.user_id == user_id).order_by(InsulinDose.datetime.desc()))
    return result.scalars().all()
