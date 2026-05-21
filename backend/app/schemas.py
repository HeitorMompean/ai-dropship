"""All Pydantic v2 request and response schemas."""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------

class ProductStatusEnum(str, Enum):
    researching = "researching"
    sample_ordered = "sample_ordered"
    listed = "listed"
    paused = "paused"
    dead = "dead"


class FulfillmentStatusEnum(str, Enum):
    pending = "pending"
    approved = "approved"
    fulfilled = "fulfilled"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"
    refunded = "refunded"


class DecisionStatusEnum(str, Enum):
    pending = "pending"
    replied = "replied"
    timeout = "timeout"
    executed = "executed"
    cancelled = "cancelled"


class ConversationDirectionEnum(str, Enum):
    outbound = "outbound"
    inbound = "inbound"


class AgentLogStatusEnum(str, Enum):
    started = "started"
    success = "success"
    failed = "failed"
    waiting_human = "waiting_human"


# ---------------------------------------------------------------------------
# Product schemas
# ---------------------------------------------------------------------------

class ProductCreate(BaseModel):
    title: str = Field(..., max_length=255)
    description: Optional[str] = None
    supplier_url: Optional[str] = None
    cost_price: float = Field(default=0.0, ge=0)
    suggested_sell_price: float = Field(default=0.0, ge=0)
    actual_sell_price: Optional[float] = Field(default=None, ge=0)
    margin: float = Field(default=0.0, ge=0)
    score_problem_solution: int = Field(default=0, ge=0, le=10)
    score_passionate_audience: int = Field(default=0, ge=0, le=10)
    score_profit_margin: int = Field(default=0, ge=0, le=10)
    score_perceived_value: int = Field(default=0, ge=0, le=10)
    score_impulse_potential: int = Field(default=0, ge=0, le=10)
    score_availability: int = Field(default=0, ge=0, le=10)
    score_trending: int = Field(default=0, ge=0, le=10)
    score_shipping: int = Field(default=0, ge=0, le=10)
    score_legal: int = Field(default=0, ge=0, le=10)
    score_repeat_purchase: int = Field(default=0, ge=0, le=10)
    score_visual_appeal: int = Field(default=0, ge=0, le=10)
    score_price_point: int = Field(default=0, ge=0, le=10)
    score_competitive_landscape: int = Field(default=0, ge=0, le=10)
    total_score: int = Field(default=0, ge=0, le=130)
    ai_analysis_json: Dict[str, Any] = Field(default_factory=dict)
    status: ProductStatusEnum = ProductStatusEnum.researching
    shopify_product_id: Optional[str] = None


class ProductUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    supplier_url: Optional[str] = None
    cost_price: Optional[float] = Field(default=None, ge=0)
    suggested_sell_price: Optional[float] = Field(default=None, ge=0)
    actual_sell_price: Optional[float] = Field(default=None, ge=0)
    margin: Optional[float] = Field(default=None, ge=0)
    score_problem_solution: Optional[int] = Field(default=None, ge=0, le=10)
    score_passionate_audience: Optional[int] = Field(default=None, ge=0, le=10)
    score_profit_margin: Optional[int] = Field(default=None, ge=0, le=10)
    score_perceived_value: Optional[int] = Field(default=None, ge=0, le=10)
    score_impulse_potential: Optional[int] = Field(default=None, ge=0, le=10)
    score_availability: Optional[int] = Field(default=None, ge=0, le=10)
    score_trending: Optional[int] = Field(default=None, ge=0, le=10)
    score_shipping: Optional[int] = Field(default=None, ge=0, le=10)
    score_legal: Optional[int] = Field(default=None, ge=0, le=10)
    score_repeat_purchase: Optional[int] = Field(default=None, ge=0, le=10)
    score_visual_appeal: Optional[int] = Field(default=None, ge=0, le=10)
    score_price_point: Optional[int] = Field(default=None, ge=0, le=10)
    score_competitive_landscape: Optional[int] = Field(default=None, ge=0, le=10)
    total_score: Optional[int] = Field(default=None, ge=0, le=130)
    ai_analysis_json: Optional[Dict[str, Any]] = None
    status: Optional[ProductStatusEnum] = None
    shopify_product_id: Optional[str] = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: Optional[str] = None
    supplier_url: Optional[str] = None
    cost_price: float
    suggested_sell_price: float
    actual_sell_price: Optional[float] = None
    margin: float
    score_problem_solution: int
    score_passionate_audience: int
    score_profit_margin: int
    score_perceived_value: int
    score_impulse_potential: int
    score_availability: int
    score_trending: int
    score_shipping: int
    score_legal: int
    score_repeat_purchase: int
    score_visual_appeal: int
    score_price_point: int
    score_competitive_landscape: int
    total_score: int
    ai_analysis_json: Dict[str, Any]
    status: ProductStatusEnum
    shopify_product_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ProductListResponse(BaseModel):
    items: List[ProductOut]
    total: int


# ---------------------------------------------------------------------------
# Order schemas
# ---------------------------------------------------------------------------

class OrderActionRequest(BaseModel):
    action: str = Field(..., pattern="^(fulfill|cancel|refund|approve)$")
    reason: Optional[str] = None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shopify_order_id: str
    customer_name: str
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    total: float
    status: str
    fraud_score: float
    fulfillment_status: FulfillmentStatusEnum
    agent_decision: Optional[str] = None
    human_override: bool
    shipping_address_json: Dict[str, Any]
    items_json: Dict[str, Any]
    created_at: datetime
    updated_at: datetime


class OrderListResponse(BaseModel):
    items: List[OrderOut]
    total: int


# ---------------------------------------------------------------------------
# Decision schemas
# ---------------------------------------------------------------------------

class DecisionCreate(BaseModel):
    agent_name: str
    decision_type: str
    context_json: Dict[str, Any] = Field(default_factory=dict)
    sms_text_sent: str
    timeout_at: datetime


class DecisionUpdate(BaseModel):
    owner_reply: Optional[str] = None
    reply_parsed_action: Optional[str] = None
    status: Optional[DecisionStatusEnum] = None
    resolved_at: Optional[datetime] = None


class DecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_name: str
    decision_type: str
    context_json: Dict[str, Any]
    sms_text_sent: str
    owner_reply: Optional[str] = None
    reply_parsed_action: Optional[str] = None
    status: DecisionStatusEnum
    timeout_at: datetime
    created_at: datetime
    resolved_at: Optional[datetime] = None


class DecisionListResponse(BaseModel):
    items: List[DecisionOut]
    total: int


class DecisionResolveRequest(BaseModel):
    action: str
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Conversation schemas
# ---------------------------------------------------------------------------

class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    decision_id: Optional[int] = None
    direction: ConversationDirectionEnum
    message_body: str
    timestamp: datetime
    message_id: Optional[str] = None


class ConversationListResponse(BaseModel):
    items: List[ConversationOut]
    total: int


class SmsInboundPayload(BaseModel):
    message: str
    phoneNumber: str
    timestamp: Optional[datetime] = None
    messageId: Optional[str] = None


# ---------------------------------------------------------------------------
# Agent schemas
# ---------------------------------------------------------------------------

class AgentStatus(BaseModel):
    name: str
    state: str  # idle, running, error, waiting_human
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    recent_error: Optional[str] = None


class AgentStatusResponse(BaseModel):
    agents: List[AgentStatus]


class AgentTriggerRequest(BaseModel):
    params: Optional[Dict[str, Any]] = Field(default_factory=dict)


class AgentLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_name: str
    action: str
    details_json: Dict[str, Any]
    status: AgentLogStatusEnum
    created_at: datetime


class AgentLogListResponse(BaseModel):
    items: List[AgentLogOut]
    total: int


# ---------------------------------------------------------------------------
# Analytics schemas
# ---------------------------------------------------------------------------

class DailySummary(BaseModel):
    date: str
    orders: int
    revenue: float
    cost: float
    profit: float
    refunds: int
    avg_order_value: float


class SummaryResponse(BaseModel):
    today: DailySummary
    yesterday: DailySummary
    this_week: Dict[str, Any]
    last_7_days: List[DailySummary]


class ProfitPoint(BaseModel):
    date: str
    profit: float
    revenue: float
    cost: float


class ProfitResponse(BaseModel):
    data: List[ProfitPoint]


class ProductPerformance(BaseModel):
    product_id: int
    title: str
    units_sold: int
    revenue: float
    profit: float
    margin_pct: float


class ProductPerformanceResponse(BaseModel):
    data: List[ProductPerformance]


# ---------------------------------------------------------------------------
# Settings schemas
# ---------------------------------------------------------------------------

class StoreSettingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    value: str
    category: str


class StoreSettingUpdate(BaseModel):
    value: str


class SettingsPatch(BaseModel):
    settings: Dict[str, str]


class SettingsResponse(BaseModel):
    settings: Dict[str, str]
    categories: Dict[str, List[str]]


class SmsSendPayload(BaseModel):
    to: str
    message: str
