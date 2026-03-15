"""
Usage tracking and billing endpoints
- Get usage stats
- Usage history
- Billing information
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from calendar import monthrange

from ..middleware.auth import get_db, get_current_user

router = APIRouter(prefix="/v1", tags=["Usage & Billing"])

# ============================================
# Endpoints
# ============================================

@router.get("/usage")
async def get_usage(current_user: dict = Depends(get_current_user)):
    """Get usage statistics for current month"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get current month stats
        cur.execute("""
            SELECT 
                COUNT(*) as total_requests,
                SUM(input_tokens) as input_tokens,
                SUM(output_tokens) as output_tokens,
                SUM(embedding_tokens) as embedding_tokens,
                SUM(total_cost_usd) as total_cost,
                COUNT(DISTINCT DATE(created_at)) as active_days
            FROM usage_logs
            WHERE company_id = %s 
                AND created_at >= date_trunc('month', now())
        """, (current_user["company_id"],))
        monthly_stats = dict(cur.fetchone())
        
        # Get usage by agent type
        cur.execute("""
            SELECT 
                agent_type,
                COUNT(*) as count,
                SUM(input_tokens + output_tokens) as tokens
            FROM usage_logs
            WHERE company_id = %s 
                AND created_at >= date_trunc('month', now())
            GROUP BY agent_type
            ORDER BY count DESC
        """, (current_user["company_id"],))
        by_agent = [dict(r) for r in cur.fetchall()]
        
        # Get daily breakdown for current month
        cur.execute("""
            SELECT 
                DATE(created_at) as date,
                COUNT(*) as requests,
                SUM(input_tokens + output_tokens) as tokens
            FROM usage_logs
            WHERE company_id = %s 
                AND created_at >= date_trunc('month', now())
            GROUP BY DATE(created_at)
            ORDER BY date ASC
        """, (current_user["company_id"],))
        daily = [
            {
                "date": r["date"].isoformat(),
                "requests": r["requests"],
                "tokens": r["tokens"] or 0
            }
            for r in cur.fetchall()
        ]
        
        # Get company quota info
        cur.execute("""
            SELECT monthly_quota, used_quota, quota_reset_at, plan
            FROM companies
            WHERE id = %s
        """, (current_user["company_id"],))
        quota_info = dict(cur.fetchone())
    
    return {
        "period": {
            "start": datetime.now().replace(day=1, hour=0, minute=0, second=0).isoformat(),
            "end": quota_info["quota_reset_at"].isoformat() if quota_info["quota_reset_at"] else None
        },
        "quota": {
            "plan": quota_info["plan"],
            "limit": quota_info["monthly_quota"],
            "used": quota_info["used_quota"],
            "remaining": quota_info["monthly_quota"] - quota_info["used_quota"],
            "percentage": round((quota_info["used_quota"] / quota_info["monthly_quota"]) * 100, 2) if quota_info["monthly_quota"] > 0 else 0
        },
        "tokens": {
            "input": monthly_stats["input_tokens"] or 0,
            "output": monthly_stats["output_tokens"] or 0,
            "embedding": monthly_stats["embedding_tokens"] or 0,
            "total": (monthly_stats["input_tokens"] or 0) + (monthly_stats["output_tokens"] or 0) + (monthly_stats["embedding_tokens"] or 0)
        },
        "requests": {
            "total": monthly_stats["total_requests"] or 0,
            "active_days": monthly_stats["active_days"] or 0,
            "avg_per_day": round((monthly_stats["total_requests"] or 0) / max(monthly_stats["active_days"] or 1, 1), 2)
        },
        "cost": {
            "total_usd": float(monthly_stats["total_cost"] or 0),
            "estimated_monthly": float(monthly_stats["total_cost"] or 0)  # Can extrapolate based on days passed
        },
        "by_agent_type": by_agent,
        "daily_breakdown": daily
    }

@router.get("/usage/history")
async def get_usage_history(
    months: int = Query(6, ge=1, le=24),
    current_user: dict = Depends(get_current_user)
):
    """Get usage history by month"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT 
                date_trunc('month', created_at) as month,
                COUNT(*) as requests,
                SUM(input_tokens) as input_tokens,
                SUM(output_tokens) as output_tokens,
                SUM(total_cost_usd) as cost
            FROM usage_logs
            WHERE company_id = %s 
                AND created_at >= date_trunc('month', now()) - interval '%s months'
            GROUP BY date_trunc('month', created_at)
            ORDER BY month DESC
        """, (current_user["company_id"], months))
        
        history = [
            {
                "month": r["month"].strftime("%Y-%m"),
                "requests": r["requests"],
                "tokens": {
                    "input": r["input_tokens"] or 0,
                    "output": r["output_tokens"] or 0,
                    "total": (r["input_tokens"] or 0) + (r["output_tokens"] or 0)
                },
                "cost_usd": float(r["cost"] or 0)
            }
            for r in cur.fetchall()
        ]
    
    return {
        "months": months,
        "history": history
    }

@router.get("/usage/endpoints")
async def get_usage_by_endpoint(
    days: int = Query(30, ge=1, le=90),
    current_user: dict = Depends(get_current_user)
):
    """Get usage breakdown by endpoint"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT 
                endpoint,
                COUNT(*) as requests,
                SUM(input_tokens + output_tokens) as tokens,
                AVG(latency_ms) as avg_latency,
                SUM(total_cost_usd) as cost
            FROM usage_logs
            WHERE company_id = %s 
                AND created_at >= now() - interval '%s days'
            GROUP BY endpoint
            ORDER BY requests DESC
        """, (current_user["company_id"], days))
        
        endpoints = [
            {
                "endpoint": r["endpoint"],
                "requests": r["requests"],
                "tokens": r["tokens"] or 0,
                "avg_latency_ms": round(float(r["avg_latency"] or 0), 2),
                "cost_usd": float(r["cost"] or 0)
            }
            for r in cur.fetchall()
        ]
    
    return {
        "period_days": days,
        "endpoints": endpoints
    }

@router.get("/billing")
async def get_billing_info(current_user: dict = Depends(get_current_user)):
    """Get billing information"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get company billing info
        cur.execute("""
            SELECT 
                plan, monthly_quota, used_quota, quota_reset_at,
                billing_email, billing_address, payment_method,
                subscription_id, subscription_status, trial_ends_at,
                created_at
            FROM companies
            WHERE id = %s
        """, (current_user["company_id"],))
        company = dict(cur.fetchone())
        
        # Get current month cost
        cur.execute("""
            SELECT SUM(total_cost_usd) as current_month_cost
            FROM usage_logs
            WHERE company_id = %s 
                AND created_at >= date_trunc('month', now())
        """, (current_user["company_id"],))
        current_cost = cur.fetchone()["current_month_cost"] or 0
        
        # Get last 3 months costs
        cur.execute("""
            SELECT 
                date_trunc('month', created_at) as month,
                SUM(total_cost_usd) as cost
            FROM usage_logs
            WHERE company_id = %s 
                AND created_at >= date_trunc('month', now()) - interval '3 months'
            GROUP BY date_trunc('month', created_at)
            ORDER BY month DESC
            LIMIT 3
        """, (current_user["company_id"],))
        past_costs = [
            {
                "month": r["month"].strftime("%Y-%m"),
                "cost_usd": float(r["cost"] or 0)
            }
            for r in cur.fetchall()
        ]
    
    # Plan pricing (example)
    plan_pricing = {
        "trial": {"monthly_fee": 0, "included_requests": 100},
        "starter": {"monthly_fee": 29, "included_requests": 1000},
        "pro": {"monthly_fee": 99, "included_requests": 5000},
        "enterprise": {"monthly_fee": 499, "included_requests": 50000}
    }
    
    plan_info = plan_pricing.get(company["plan"], plan_pricing["trial"])
    
    return {
        "plan": {
            "name": company["plan"],
            "monthly_fee_usd": plan_info["monthly_fee"],
            "included_requests": plan_info["included_requests"],
            "quota_limit": company["monthly_quota"],
            "status": company["subscription_status"],
            "trial_ends_at": company["trial_ends_at"].isoformat() if company["trial_ends_at"] else None
        },
        "billing_details": {
            "email": company["billing_email"],
            "address": company["billing_address"],
            "payment_method": company["payment_method"]
        },
        "current_period": {
            "start": datetime.now().replace(day=1, hour=0, minute=0, second=0).isoformat(),
            "end": company["quota_reset_at"].isoformat() if company["quota_reset_at"] else None,
            "usage_cost_usd": float(current_cost),
            "estimated_total": plan_info["monthly_fee"] + float(current_cost)
        },
        "past_invoices": past_costs,
        "next_billing_date": company["quota_reset_at"].isoformat() if company["quota_reset_at"] else None
    }
