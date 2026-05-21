"""Initial migration: create all tables.

Revision ID: 000000000001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '000000000001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'products',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('supplier_url', sa.String(length=512), nullable=True),
        sa.Column('cost_price', sa.Float(), nullable=False),
        sa.Column('suggested_sell_price', sa.Float(), nullable=False),
        sa.Column('actual_sell_price', sa.Float(), nullable=True),
        sa.Column('margin', sa.Float(), nullable=False),
        sa.Column('score_problem_solution', sa.Integer(), nullable=False),
        sa.Column('score_passionate_audience', sa.Integer(), nullable=False),
        sa.Column('score_profit_margin', sa.Integer(), nullable=False),
        sa.Column('score_perceived_value', sa.Integer(), nullable=False),
        sa.Column('score_impulse_potential', sa.Integer(), nullable=False),
        sa.Column('score_availability', sa.Integer(), nullable=False),
        sa.Column('score_trending', sa.Integer(), nullable=False),
        sa.Column('score_shipping', sa.Integer(), nullable=False),
        sa.Column('score_legal', sa.Integer(), nullable=False),
        sa.Column('score_repeat_purchase', sa.Integer(), nullable=False),
        sa.Column('score_visual_appeal', sa.Integer(), nullable=False),
        sa.Column('score_price_point', sa.Integer(), nullable=False),
        sa.Column('score_competitive_landscape', sa.Integer(), nullable=False),
        sa.Column('total_score', sa.Integer(), nullable=False),
        sa.Column('ai_analysis_json', sa.JSON(), nullable=False),
        sa.Column('status', sa.Enum('researching', 'sample_ordered', 'listed', 'paused', 'dead', name='productstatus'), nullable=False),
        sa.Column('shopify_product_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_products_id', 'products', ['id'], unique=False)
    op.create_index('ix_products_shopify_product_id', 'products', ['shopify_product_id'], unique=False)

    op.create_table(
        'orders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('shopify_order_id', sa.String(length=64), nullable=False),
        sa.Column('customer_name', sa.String(length=255), nullable=False),
        sa.Column('customer_phone', sa.String(length=32), nullable=True),
        sa.Column('customer_email', sa.String(length=255), nullable=True),
        sa.Column('total', sa.Float(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('fraud_score', sa.Float(), nullable=False),
        sa.Column('fulfillment_status', sa.Enum('pending', 'approved', 'fulfilled', 'shipped', 'delivered', 'cancelled', 'refunded', name='orderfulfillmentstatus'), nullable=False),
        sa.Column('agent_decision', sa.String(length=32), nullable=True),
        sa.Column('human_override', sa.Boolean(), nullable=False),
        sa.Column('shipping_address_json', sa.JSON(), nullable=False),
        sa.Column('items_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shopify_order_id')
    )
    op.create_index('ix_orders_id', 'orders', ['id'], unique=False)
    op.create_index('ix_orders_shopify_order_id', 'orders', ['shopify_order_id'], unique=False)

    op.create_table(
        'decisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_name', sa.String(length=64), nullable=False),
        sa.Column('decision_type', sa.String(length=64), nullable=False),
        sa.Column('context_json', sa.JSON(), nullable=False),
        sa.Column('sms_text_sent', sa.Text(), nullable=False),
        sa.Column('owner_reply', sa.Text(), nullable=True),
        sa.Column('reply_parsed_action', sa.String(length=64), nullable=True),
        sa.Column('status', sa.Enum('pending', 'replied', 'timeout', 'executed', 'cancelled', name='decisionstatus'), nullable=False),
        sa.Column('timeout_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_decisions_id', 'decisions', ['id'], unique=False)

    op.create_table(
        'conversations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('decision_id', sa.Integer(), nullable=True),
        sa.Column('direction', sa.Enum('outbound', 'inbound', name='conversationdirection'), nullable=False),
        sa.Column('message_body', sa.Text(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('message_id', sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(['decision_id'], ['decisions.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_conversations_id', 'conversations', ['id'], unique=False)
    op.create_index('ix_conversations_decision_id', 'conversations', ['decision_id'], unique=False)

    op.create_table(
        'agent_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_name', sa.String(length=64), nullable=False),
        sa.Column('action', sa.String(length=128), nullable=False),
        sa.Column('details_json', sa.JSON(), nullable=False),
        sa.Column('status', sa.Enum('started', 'success', 'failed', 'waiting_human', name='agentlogstatus'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_agent_logs_id', 'agent_logs', ['id'], unique=False)
    op.create_index('ix_agent_logs_agent_name', 'agent_logs', ['agent_name'], unique=False)

    op.create_table(
        'price_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('competitor_url', sa.String(length=512), nullable=True),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('scraped_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['products.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_price_snapshots_id', 'price_snapshots', ['id'], unique=False)
    op.create_index('ix_price_snapshots_product_id', 'price_snapshots', ['product_id'], unique=False)

    op.create_table(
        'store_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=128), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key')
    )
    op.create_index('ix_store_settings_id', 'store_settings', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_store_settings_id', table_name='store_settings')
    op.drop_table('store_settings')
    op.drop_index('ix_price_snapshots_product_id', table_name='price_snapshots')
    op.drop_index('ix_price_snapshots_id', table_name='price_snapshots')
    op.drop_table('price_snapshots')
    op.drop_index('ix_agent_logs_agent_name', table_name='agent_logs')
    op.drop_index('ix_agent_logs_id', table_name='agent_logs')
    op.drop_table('agent_logs')
    op.drop_index('ix_conversations_decision_id', table_name='conversations')
    op.drop_index('ix_conversations_id', table_name='conversations')
    op.drop_table('conversations')
    op.drop_index('ix_decisions_id', table_name='decisions')
    op.drop_table('decisions')
    op.drop_index('ix_orders_shopify_order_id', table_name='orders')
    op.drop_index('ix_orders_id', table_name='orders')
    op.drop_table('orders')
    op.drop_index('ix_products_shopify_product_id', table_name='products')
    op.drop_index('ix_products_id', table_name='products')
    op.drop_table('products')
