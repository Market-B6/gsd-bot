from sqlalchemy import Column, Integer, String, DateTime, Float, Boolean, ForeignKey, Enum as SQLEnum, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base

class SubscriptionTier(str, enum.Enum):
    FREE = "free"
    PRO = "pro"

class GlucoseType(str, enum.Enum):
    FASTING = "fasting"
    POSTMEAL = "postmeal"

class InsulinType(str, enum.Enum):
    SHORT = "short"
    LONG = "long"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    due_date = Column(DateTime, nullable=True)
    timezone = Column(String, default="Europe/Moscow")
    lang = Column(String, default="ru")
    subscription_tier = Column(SQLEnum(SubscriptionTier), default=SubscriptionTier.FREE)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())

    meals = relationship("Meal", back_populates="user", cascade="all, delete-orphan")
    glucose_readings = relationship("GlucoseReading", back_populates="user", cascade="all, delete-orphan")
    insulin_doses = relationship("InsulinDose", back_populates="user", cascade="all, delete-orphan")
    timers = relationship("Timer", back_populates="user", cascade="all, delete-orphan")
    events = relationship("UserEvent", back_populates="user", cascade="all, delete-orphan")

class Meal(Base):
    __tablename__ = "meals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    datetime = Column(DateTime, nullable=False, index=True)
    description = Column(String, nullable=False)
    photo_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="meals")
    glucose_readings = relationship("GlucoseReading", back_populates="meal")
    timers = relationship("Timer", back_populates="meal", cascade="all, delete-orphan")

class GlucoseReading(Base):
    __tablename__ = "glucose_readings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    meal_id = Column(Integer, ForeignKey("meals.id"), nullable=True, index=True)
    datetime = Column(DateTime, nullable=False, index=True)
    value = Column(Float, nullable=False)
    type = Column(SQLEnum(GlucoseType), nullable=False)
    is_normal = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="glucose_readings")
    meal = relationship("Meal", back_populates="glucose_readings")

class InsulinDose(Base):
    __tablename__ = "insulin_doses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    datetime = Column(DateTime, nullable=False, index=True)
    units = Column(Float, nullable=False)
    type = Column(SQLEnum(InsulinType), nullable=False)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="insulin_doses")

class Timer(Base):
    __tablename__ = "timers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    meal_id = Column(Integer, ForeignKey("meals.id"), nullable=False, index=True)
    start_time = Column(DateTime, nullable=False)
    notify_at = Column(DateTime, nullable=False, index=True)
    is_notified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="timers")
    meal = relationship("Meal", back_populates="timers")

class UserEvent(Base):
    __tablename__ = "user_events"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="events")
