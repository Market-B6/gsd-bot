"""PRO features: subscriptions, payments, vitals, kicks, referral, postpartum, doctors, recipes, ai_tasks

Revision ID: 002
Revises: 001
Create Date: 2026-08-03

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PAYMENT_PROVIDER = sa.Enum('STARS', 'YOOKASSA', 'STRIPE', name='paymentprovider')
PAYMENT_STATUS = sa.Enum('PENDING', 'PAID', 'REFUNDED', 'FAILED', name='paymentstatus')
PRODUCT_TYPE = sa.Enum(
    'SUB_MONTHLY', 'SUB_YEARLY', 'PDF_REPORT', 'AI_PHOTO_PACK', 'COURSE', 'DOCTOR_SEAT', 'CONSULTATION',
    name='producttype',
)
POSTPARTUM_STAGE = sa.Enum(
    'PREGNANT', 'POSTPARTUM', 'OGTT_6W_DONE', 'OGTT_1Y_DONE', name='postpartumstage',
)


def upgrade() -> None:
    # Extend users
    op.add_column('users', sa.Column('subscription_expires_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('trial_used', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('users', sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('users', sa.Column('postpartum_stage', POSTPARTUM_STAGE, nullable=False, server_default='PREGNANT'))
    op.add_column('users', sa.Column('birth_date', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('reminder_fasting_time', sa.String(), nullable=False, server_default='07:30'))
    op.add_column('users', sa.Column('reminder_evening_time', sa.String(), nullable=False, server_default='21:00'))
    op.add_column('users', sa.Column('reminders_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('users', sa.Column('referrer_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))
    op.add_column('users', sa.Column('referral_code', sa.String(), nullable=True))
    op.create_index('ix_users_referral_code', 'users', ['referral_code'], unique=True)
    op.add_column('users', sa.Column('ai_photos_used_month', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('ai_photos_extra', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('pdf_reports_used_month', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('quota_reset_at', sa.DateTime(), nullable=True))

    op.add_column('user_events', sa.Column('payload', sa.String(), nullable=True))

    op.create_table(
        'payments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('provider', PAYMENT_PROVIDER, nullable=False),
        sa.Column('product', PRODUCT_TYPE, nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(), nullable=False, server_default='XTR'),
        sa.Column('status', PAYMENT_STATUS, nullable=False, server_default='PENDING'),
        sa.Column('provider_charge_id', sa.String(), nullable=True),
        sa.Column('invoice_payload', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_payments_status', 'payments', ['status'])
    op.create_index('ix_payments_provider_charge_id', 'payments', ['provider_charge_id'])
    op.create_index('ix_payments_invoice_payload', 'payments', ['invoice_payload'])

    op.create_table(
        'weight_entries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('datetime', sa.DateTime(), nullable=False, index=True),
        sa.Column('weight_kg', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )

    op.create_table(
        'bp_entries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('datetime', sa.DateTime(), nullable=False, index=True),
        sa.Column('systolic', sa.Integer(), nullable=False),
        sa.Column('diastolic', sa.Integer(), nullable=False),
        sa.Column('pulse', sa.Integer(), nullable=True),
        sa.Column('is_alert', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )

    op.create_table(
        'kick_sessions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('start_time', sa.DateTime(), nullable=False, index=True),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('kicks_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_alert', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )

    op.create_table(
        'recipes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('category', sa.String(), nullable=False, index=True),
        sa.Column('meal_time', sa.String(), nullable=True),
        sa.Column('ingredients', sa.String(), nullable=False),
        sa.Column('instructions', sa.String(), nullable=False),
        sa.Column('protein_g', sa.Float(), nullable=True),
        sa.Column('fat_g', sa.Float(), nullable=True),
        sa.Column('carb_g', sa.Float(), nullable=True),
        sa.Column('xe', sa.Float(), nullable=True),
        sa.Column('kcal', sa.Integer(), nullable=True),
        sa.Column('gi', sa.Integer(), nullable=True),
        sa.Column('is_pro', sa.Boolean(), nullable=False, server_default=sa.text('false'), index=True),
        sa.Column('photo_url', sa.String(), nullable=True),
        sa.Column('tags', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )

    op.create_table(
        'doctors',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tg_id', sa.BigInteger(), nullable=True, unique=True, index=True),
        sa.Column('email', sa.String(), nullable=False, unique=True, index=True),
        sa.Column('full_name', sa.String(), nullable=False),
        sa.Column('clinic', sa.String(), nullable=True),
        sa.Column('access_token', sa.String(), nullable=False, unique=True, index=True),
        sa.Column('subscription_expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )

    op.create_table(
        'doctor_patients',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('invite_code', sa.String(), nullable=False, unique=True, index=True),
        sa.Column('approved', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )

    op.create_table(
        'ai_tasks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('task_type', sa.String(), nullable=False, index=True),
        sa.Column('status', sa.String(), nullable=False, server_default='pending', index=True),
        sa.Column('input_data', sa.String(), nullable=True),
        sa.Column('result_data', sa.String(), nullable=True),
        sa.Column('error', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'postpartum_reminders',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('reminder_type', sa.String(), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(), nullable=False, index=True),
        sa.Column('sent', sa.Boolean(), nullable=False, server_default=sa.text('false'), index=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )

    op.create_table(
        'referrals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('referrer_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('referee_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, unique=True, index=True),
        sa.Column('reward_granted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )


def downgrade() -> None:
    op.drop_table('referrals')
    op.drop_table('postpartum_reminders')
    op.drop_table('ai_tasks')
    op.drop_table('doctor_patients')
    op.drop_table('doctors')
    op.drop_table('recipes')
    op.drop_table('kick_sessions')
    op.drop_table('bp_entries')
    op.drop_table('weight_entries')
    op.drop_table('payments')
    op.drop_column('user_events', 'payload')
    for col in [
        'quota_reset_at', 'pdf_reports_used_month', 'ai_photos_extra', 'ai_photos_used_month',
        'referral_code', 'referrer_id', 'reminders_enabled', 'reminder_evening_time',
        'reminder_fasting_time', 'birth_date', 'postpartum_stage', 'is_admin', 'trial_used',
        'subscription_expires_at',
    ]:
        op.drop_column('users', col)
    for enum_name in ('paymentprovider', 'paymentstatus', 'producttype', 'postpartumstage'):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
