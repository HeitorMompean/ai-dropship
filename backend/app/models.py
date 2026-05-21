"""All SQLAlchemy ORM models for the AI Dropshipping Store."""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    Text,
    DateTime,
    ForeignKey,
    JSON,
    Enum as SQLEnum,
    create_engine,
)
from sqlalchemy.orm import relationship
from app.database import Base


class ProductStatus(PyEnum):
    researching = "researching"
    sample_ordered = "sample_ordered"
    listed = "listed"
    paused = "paused"
    dead = "dead"


class OrderFulfillmentStatus(PyEnum):
    pending = "pending"
    approved = "approved"
    fulfilled = "fulfilled"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"
    refunded = "refunded"


class DecisionStatus(PyEnum):
    pending = "pending"
    replied = "replied"
    timeout = "timeout"
    executed = "executed"
    cancelled = "cancelled"


class ConversationDirection(PyEnum):
    outbound = "outbound"
    inbound = "inbound"


class AgentLogStatus(PyEnum):
    started = "started"
    success = "success"
    failed = "failed"
    waiting_human = "waiting_human"


class Product(Base):
    """A dropshipping product candidate or live listing."""

    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    supplier_url = Column(String(512), nullable=True)
    cost_price = Column(Float, nullable=False, default=0.0)
    suggested_sell_price = Column(Float, nullable=False, default=0.0)
    actual_sell_price = Column(Float, nullable=True)
    margin = Column(Float, nullable=False, default=0.0)

    # 13-factor scoring framework (0-10 each, total 0-130)
    score_problem_solution = Column(Integer, nullable=False, default=0)
    score_passionate_audience = Column(Integer, nullable=False, default=0)
    score_profit_margin = Column(Integer, nullable=False, default=0)
    score_perceived_value = Column(Integer, nullable=False, default=0)
    score_impulse_potential = Column(Integer, nullable=False, default=0)
    score_availability = Column(Integer, nullable=False, default=0)
    score_trending = Column(Integer, nullable=False, default=0)
    score_shipping = Column(Integer, nullable=False, default=0)
    score_legal = Column(Integer, nullable=False, default=0)
    score_repeat_purchase = Column(Integer, nullable=False, default=0)
    score_visual_appeal = Column(Integer, nullable=False, default=0)
    score_price_point = Column(Integer, nullable=False, default=0)
    score_competitive_landscape = Column(Integer, nullable=False, default=0)
    total_score = Column(Integer, nullable=False, default=0)

    ai_analysis_json = Column(JSON, nullable=False, default=dict)
    status = Column(SQLEnum(ProductStatus), nullable=False, default=ProductStatus.researching)
    shopify_product_id = Column(String(64), nullable=True, index=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    price_snapshots = relationship("PriceSnapshot", back_populates="product", cascade="all, delete-orphan")


class Order(Base):
    """A Shopify order synced into the system."""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    shopify_order_id = Column(String(64), nullable=False, unique=True, index=True)
    customer_name = Column(String(255), nullable=False)
    customer_phone = Column(String(32), nullable=True)
    customer_email = Column(String(255), nullable=True)
    total = Column(Float, nullable=False, default=0.0)
    status = Column(String(32), nullable=False, default="open")
    fraud_score = Column(Float, nullable=False, default=0.0)
    fulfillment_status = Column(
        SQLEnum(OrderFulfillmentStatus),
        nullable=False,
        default=OrderFulfillmentStatus.pending,
    )
    agent_decision = Column(String(32), nullable=True)
    human_override = Column(Boolean, nullable=False, default=False)
    shipping_address_json = Column(JSON, nullable=False, default=dict)
    items_json = Column(JSON, nullable=False, default=dict)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class Decision(Base):
    """A human-in-the-loop decision awaiting owner input."""

    __tablename__ = "decisions"

    id = Column(Integer, primary_key=True, index=True)
    agent_name = Column(String(64), nullable=False)
    decision_type = Column(String(64), nullable=False)
    context_json = Column(JSON, nullable=False, default=dict)
    sms_text_sent = Column(Text, nullable=False)
    owner_reply = Column(Text, nullable=True)
    reply_parsed_action = Column(String(64), nullable=True)
    status = Column(SQLEnum(DecisionStatus), nullable=False, default=DecisionStatus.pending)
    timeout_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    conversations = relationship("Conversation", back_populates="decision")


class Conversation(Base):
    """SMS conversation history."""

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    decision_id = Column(Integer, ForeignKey("decisions.id"), nullable=True, index=True)
    direction = Column(SQLEnum(ConversationDirection), nullable=False)
    message_body = Column(Text, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    message_id = Column(String(128), nullable=True)

    decision = relationship("Decision", back_populates="conversations")


class AgentLog(Base):
    """Audit log of agent actions."""

    __tablename__ = "agent_logs"

    id = Column(Integer, primary_key=True, index=True)
    agent_name = Column(String(64), nullable=False, index=True)
    action = Column(String(128), nullable=False)
    details_json = Column(JSON, nullable=False, default=dict)
    status = Column(SQLEnum(AgentLogStatus), nullable=False, default=AgentLogStatus.started)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class PriceSnapshot(Base):
    """Competitor price snapshot for a product."""

    __tablename__ = "price_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    competitor_url = Column(String(512), nullable=True)
    price = Column(Float, nullable=False, default=0.0)
    scraped_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    product = relationship("Product", back_populates="price_snapshots")


class StoreSetting(Base):
    """Key-value store settings."""

    __tablename__ = "store_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(128), nullable=False, unique=True)
    value = Column(Text, nullable=False)
    category = Column(String(64), nullable=False, default="general")
