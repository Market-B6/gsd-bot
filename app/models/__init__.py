from sqlalchemy import Column, Integer, String, DateTime, Float, Boolean, ForeignKey, Enum as SQLEnum, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base

class SubscriptionTier(str, enum.Enum):
    FREE = "free"
    PRO = "pro"

class SubscriptionStatus(str, enum.Enum):
    TRIAL = "trial"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    REFUNDED = "refunded"
    FAILED = "failed"

class PaymentProvider(str, enum.Enum):
    STARS = "stars"
    YOOKASSA = "yookassa"
    STRIPE = "stripe"

class ProductType(str, enum.Enum):
    SUB_MONTHLY = "sub_monthly"
    SUB_YEARLY = "sub_yearly"
    PDF_REPORT = "pdf_report"
    AI_PHOTO_PACK = "ai_photo_pack"
    COURSE = "course"
    DOCTOR_SEAT = "doctor_seat"
    CONSULTATION = "consultation"

class PostpartumStage(str, enum.Enum):
    PREGNANT = "pregnant"
    POSTPARTUM = "postpartum"
    OGTT_6W_DONE = "ogtt_6w_done"
    OGTT_1Y_DONE = "ogtt_1y_done"

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
    subscription_expires_at = Column(DateTime, nullable=True)
    trial_used = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)

    # Fertility/pregnancy
    postpartum_stage = Column(SQLEnum(PostpartumStage), default=PostpartumStage.PREGNANT)
    birth_date = Column(DateTime, nullable=True)

    # Reminders customization
    reminder_fasting_time = Column(String, default="07:30")
    reminder_evening_time = Column(String, default="21:00")
    reminders_enabled = Column(Boolean, default=True)

    # Referral
    referrer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    referral_code = Column(String, unique=True, nullable=True, index=True)

    # Quota counters (reset monthly)
    ai_photos_used_month = Column(Integer, default=0)
    ai_photos_extra = Column(Integer, default=0)  # bought packs
    pdf_reports_used_month = Column(Integer, default=0)
    quota_reset_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=func.now())

    meals = relationship("Meal", back_populates="user", cascade="all, delete-orphan")
    glucose_readings = relationship("GlucoseReading", back_populates="user", cascade="all, delete-orphan")
    insulin_doses = relationship("InsulinDose", back_populates="user", cascade="all, delete-orphan")
    timers = relationship("Timer", back_populates="user", cascade="all, delete-orphan")
    events = relationship("UserEvent", back_populates="user", cascade="all, delete-orphan")
    weight_entries = relationship("WeightEntry", back_populates="user", cascade="all, delete-orphan")
    bp_entries = relationship("BPEntry", back_populates="user", cascade="all, delete-orphan")
    kick_sessions = relationship("KickSession", back_populates="user", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="user", cascade="all, delete-orphan")

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
    payload = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="events")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(SQLEnum(PaymentProvider), nullable=False)
    product = Column(SQLEnum(ProductType), nullable=False)
    amount = Column(Float, nullable=False)  # in provider currency units (XTR / RUB)
    currency = Column(String, default="XTR")
    status = Column(SQLEnum(PaymentStatus), default=PaymentStatus.PENDING, index=True)
    provider_charge_id = Column(String, nullable=True, index=True)  # telegram_payment_charge_id
    invoice_payload = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=func.now())
    paid_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="payments")


class WeightEntry(Base):
    __tablename__ = "weight_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    datetime = Column(DateTime, nullable=False, index=True)
    weight_kg = Column(Float, nullable=False)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="weight_entries")


class BPEntry(Base):
    __tablename__ = "bp_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    datetime = Column(DateTime, nullable=False, index=True)
    systolic = Column(Integer, nullable=False)
    diastolic = Column(Integer, nullable=False)
    pulse = Column(Integer, nullable=True)
    is_alert = Column(Boolean, default=False)  # >=140/90 preeclampsia risk
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="bp_entries")


class KickSession(Base):
    __tablename__ = "kick_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    start_time = Column(DateTime, nullable=False, index=True)
    end_time = Column(DateTime, nullable=True)
    kicks_count = Column(Integer, default=0)
    is_alert = Column(Boolean, default=False)  # <10 kicks in 2h
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="kick_sessions")


class Recipe(Base):
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    category = Column(String, nullable=False, index=True)  # breakfast/lunch/dinner/snack
    meal_time = Column(String, nullable=True)
    ingredients = Column(String, nullable=False)
    instructions = Column(String, nullable=False)
    protein_g = Column(Float, nullable=True)
    fat_g = Column(Float, nullable=True)
    carb_g = Column(Float, nullable=True)
    xe = Column(Float, nullable=True)  # bread units
    kcal = Column(Integer, nullable=True)
    gi = Column(Integer, nullable=True)  # glycemic index
    is_pro = Column(Boolean, default=False, index=True)
    photo_url = Column(String, nullable=True)
    tags = Column(String, nullable=True)  # comma-separated
    created_at = Column(DateTime, default=func.now())


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(BigInteger, unique=True, nullable=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    full_name = Column(String, nullable=False)
    clinic = Column(String, nullable=True)
    access_token = Column(String, unique=True, nullable=False, index=True)
    subscription_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())

    patient_links = relationship("DoctorPatient", back_populates="doctor", cascade="all, delete-orphan")


class DoctorPatient(Base):
    __tablename__ = "doctor_patients"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    invite_code = Column(String, unique=True, nullable=False, index=True)
    approved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())

    doctor = relationship("Doctor", back_populates="patient_links")


class AITask(Base):
    __tablename__ = "ai_tasks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    task_type = Column(String, nullable=False, index=True)  # photo_meal, weekly_analysis, chat
    status = Column(String, default="pending", index=True)  # pending/processing/done/failed
    input_data = Column(String, nullable=True)  # json
    result_data = Column(String, nullable=True)  # json
    error = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())
    completed_at = Column(DateTime, nullable=True)


class PostpartumReminder(Base):
    __tablename__ = "postpartum_reminders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    reminder_type = Column(String, nullable=False)  # ogtt_6w / ogtt_1y / weight_6m
    scheduled_at = Column(DateTime, nullable=False, index=True)
    sent = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=func.now())


class Referral(Base):
    __tablename__ = "referrals"

    id = Column(Integer, primary_key=True, index=True)
    referrer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    referee_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, unique=True)
    reward_granted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
