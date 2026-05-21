"""Analytics engine for profit calculation and store metrics."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import random

logger = logging.getLogger(__name__)


class AnalyticsEngine:
    """Calculate profit, margins, and dashboard metrics."""

    @staticmethod
    def calculate_order_profit(
        revenue: float,
        cost_price: float,
        shipping_cost: float = 5.0,
        ad_spend: float = 0.0,
        payment_fee_pct: float = 2.9,
        payment_fee_fixed: float = 0.30,
    ) -> Dict[str, float]:
        """Calculate true profit for an order.

        Args:
            revenue: Total customer payment.
            cost_price: Product cost from supplier.
            shipping_cost: Estimated shipping per unit.
            ad_spend: Ad spend attributed to this order.
            payment_fee_pct: Payment processor percentage fee.
            payment_fee_fixed: Payment processor fixed fee.

        Returns:
            Dict with revenue, costs, net_profit, margin_pct.
        """
        payment_fees = revenue * (payment_fee_pct / 100) + payment_fee_fixed
        total_cost = cost_price + shipping_cost + ad_spend + payment_fees
        net_profit = revenue - total_cost
        margin_pct = (net_profit / revenue * 100) if revenue else 0.0
        return {
            "revenue": round(revenue, 2),
            "product_cost": round(cost_price, 2),
            "shipping_cost": round(shipping_cost, 2),
            "ad_spend": round(ad_spend, 2),
            "payment_fees": round(payment_fees, 2),
            "total_cost": round(total_cost, 2),
            "net_profit": round(net_profit, 2),
            "margin_pct": round(margin_pct, 2),
        }

    @staticmethod
    def generate_daily_summary(
        orders: List[Dict[str, Any]], refunds: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Aggregate orders into a daily summary.

        Expects orders as dicts with keys: total, cost_price, shipping_cost, ad_spend.
        """
        refunds = refunds or []
        total_revenue = sum(o.get("total", 0) for o in orders)
        total_cost = sum(
            o.get("cost_price", 0) + o.get("shipping_cost", 5.0) + o.get("ad_spend", 0)
            for o in orders
        )
        # Add payment fees
        total_fees = sum(
            o.get("total", 0) * 0.029 + 0.30 for o in orders
        )
        refund_amount = sum(r.get("amount", 0) for r in refunds)
        net_profit = total_revenue - total_cost - total_fees - refund_amount
        avg_order = (total_revenue / len(orders)) if orders else 0.0
        return {
            "orders": len(orders),
            "revenue": round(total_revenue, 2),
            "cost": round(total_cost, 2),
            "payment_fees": round(total_fees, 2),
            "refunds": len(refunds),
            "refund_amount": round(refund_amount, 2),
            "profit": round(net_profit, 2),
            "avg_order_value": round(avg_order, 2),
        }

    @staticmethod
    def get_ad_performance_mock(days: int = 7) -> Dict[str, Any]:
        """Return mock ad performance metrics for the dashboard."""
        return {
            "period_days": days,
            "spend": round(random.uniform(150, 800), 2),
            "impressions": random.randint(5000, 50000),
            "clicks": random.randint(200, 3000),
            "conversions": random.randint(5, 80),
            "roas": round(random.uniform(1.2, 4.5), 2),
            "cpc": round(random.uniform(0.40, 2.50), 2),
        }

    @staticmethod
    def get_daily_metrics_mock() -> Dict[str, Any]:
        """Return mock daily metrics for agent monitoring."""
        return {
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "visitors": random.randint(100, 2000),
            "orders": random.randint(0, 30),
            "revenue": round(random.uniform(0, 1500), 2),
            "profit": round(random.uniform(-50, 500), 2),
            "conversion_rate": round(random.uniform(0.5, 3.5), 2),
            "cart_abandonment": round(random.uniform(60, 85), 1),
            "return_rate": round(random.uniform(0, 8), 1),
        }

    @staticmethod
    def get_product_performance_mock(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate mock performance data for a list of products."""
        results = []
        for p in products:
            units = random.randint(0, 100)
            revenue = units * (p.get("actual_sell_price", 49.99) or 49.99)
            cost = units * p.get("cost_price", 10.0)
            profit = revenue - cost
            margin = (profit / revenue * 100) if revenue else 0.0
            results.append(
                {
                    "product_id": p.get("id", 0),
                    "title": p.get("title", "Unknown"),
                    "units_sold": units,
                    "revenue": round(revenue, 2),
                    "profit": round(profit, 2),
                    "margin_pct": round(margin, 2),
                }
            )
        return results


analytics_engine = AnalyticsEngine()
