"""initial migration

Revision ID: 001
Revises:
Create Date: 2026-07-31

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tg_id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(), nullable=True),
        sa.Column('full_name', sa.String(), nullable=True),
        sa.Column('due_date', sa.DateTime(), nullable=True),
        sa.Column('timezone', sa.String(), nullable=False, server_default='Europe/Moscow'),
        sa.Column('lang', sa.String(), nullable=False, server_default='ru'),
        sa.Column('subscription_tier', sa.Enum('FREE', 'PRO', name='subscriptiontier'), nullable=False, server_default='FREE'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_tg_id', 'users', ['tg_id'], unique=True)

    op.create_table(
        'meals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('datetime', sa.DateTime(), nullable=False),
        sa.Column('description', sa.String(), nullable=False),
        sa.Column('photo_url', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_meals_user_id', 'meals', ['user_id'])
    op.create_index('ix_meals_datetime', 'meals', ['datetime'])

    op.create_table(
        'glucose_readings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('meal_id', sa.Integer(), nullable=True),
        sa.Column('datetime', sa.DateTime(), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('type', sa.Enum('FASTING', 'POSTMEAL', name='glucosetype'), nullable=False),
        sa.Column('is_normal', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['meal_id'], ['meals.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_glucose_user_id', 'glucose_readings', ['user_id'])
    op.create_index('ix_glucose_datetime', 'glucose_readings', ['datetime'])

    op.create_table(
        'insulin_doses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('datetime', sa.DateTime(), nullable=False),
        sa.Column('units', sa.Float(), nullable=False),
        sa.Column('type', sa.Enum('SHORT', 'LONG', name='insulintype'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_insulin_user_id', 'insulin_doses', ['user_id'])
    op.create_index('ix_insulin_datetime', 'insulin_doses', ['datetime'])

    op.create_table(
        'timers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('meal_id', sa.Integer(), nullable=False),
        sa.Column('start_time', sa.DateTime(), nullable=False),
        sa.Column('notify_at', sa.DateTime(), nullable=False),
        sa.Column('is_notified', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['meal_id'], ['meals.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_timers_user_id', 'timers', ['user_id'])
    op.create_index('ix_timers_notify_at', 'timers', ['notify_at'])

def downgrade() -> None:
    op.drop_table('timers')
    op.drop_table('insulin_doses')
    op.drop_table('glucose_readings')
    op.drop_table('meals')
    op.drop_table('users')
    op.execute('DROP TYPE IF EXISTS subscriptiontier')
    op.execute('DROP TYPE IF EXISTS glucosetype')
    op.execute('DROP TYPE IF EXISTS insulintype')
