"""
API Key management endpoints
- List, create, revoke API keys
"""
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import Optional, List
from psycopg2.extras import RealDictCursor
from datetime import datetime
import secrets
import hashlib

from ..middleware.auth import get_db, get_current_user, require_role

router = APIRouter(prefix="/v1/keys", tags=["API Keys"])

# ============================================
# Models
# ============================================

class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)
    permissions: Optional[List[str]] = ["read", "ask", "review", "draft"]
    rate_limit: Optional[int] = 60
    expires_in_days: Optional[int] = None

# ============================================
# Endpoints
# ============================================

@router.get("")
async def list_keys(current_user: dict = Depends(get_current_user)):
    """List all API keys for the company"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, name, key_prefix, permissions, rate_limit, is_active,
                   last_used_at, expires_at, created_at
            FROM api_keys
            WHERE company_id = %s
            ORDER BY created_at DESC
        """, (current_user["company_id"],))
        keys = cur.fetchall()
    
    return {
        "keys": [{
            "id": str(k["id"]),
            "name": k["name"],
            "key_prefix": k["key_prefix"],
            "permissions": k["permissions"],
            "rate_limit": k["rate_limit"],
            "is_active": k["is_active"],
            "last_used_at": k["last_used_at"].isoformat() if k["last_used_at"] else None,
            "expires_at": k["expires_at"].isoformat() if k["expires_at"] else None,
            "created_at": k["created_at"].isoformat()
        } for k in keys]
    }

@router.post("")
async def create_key(
    data: CreateKeyRequest,
    current_user: dict = Depends(require_role("admin"))
):
    """Create a new API key (admin only)"""
    # Validate permissions
    valid_permissions = ["read", "ask", "review", "draft", "compliance", "batch"]
    for perm in data.permissions:
        if perm not in valid_permissions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid permission: {perm}. Valid: {', '.join(valid_permissions)}"
            )
    
    # Generate API key
    api_key = f"lak_{secrets.token_hex(24)}"
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    key_prefix = api_key[:8]
    
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Check key count limit (optional)
        cur.execute(
            "SELECT COUNT(*) as key_count FROM api_keys WHERE company_id = %s AND is_active = true",
            (current_user["company_id"],)
        )
        key_count = cur.fetchone()["key_count"]
        
        # Limit based on plan (example: trial = 2 keys, pro = 10)
        plan_limits = {"trial": 2, "starter": 5, "pro": 10, "enterprise": 50}
        max_keys = plan_limits.get(current_user["plan"], 2)
        
        if key_count >= max_keys:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key limit reached for {current_user['plan']} plan. Maximum: {max_keys}"
            )
        
        # Calculate expiry
        expires_at = None
        if data.expires_in_days:
            cur.execute("SELECT now() + interval '%s days' as expiry", (data.expires_in_days,))
            expires_at = cur.fetchone()["expiry"]
        
        # Create key
        cur.execute("""
            INSERT INTO api_keys (company_id, name, key_hash, key_prefix, permissions, rate_limit, expires_at, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, true)
            RETURNING id, created_at
        """, (
            current_user["company_id"],
            data.name,
            key_hash,
            key_prefix,
            data.permissions,
            data.rate_limit,
            expires_at
        ))
        key_info = dict(cur.fetchone())
        conn.commit()
    
    return {
        "message": "API key created successfully",
        "key": {
            "id": str(key_info["id"]),
            "name": data.name,
            "api_key": api_key,
            "key_prefix": key_prefix,
            "permissions": data.permissions,
            "rate_limit": data.rate_limit,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "created_at": key_info["created_at"].isoformat()
        },
        "warning": "⚠️ Save this API key now! It cannot be retrieved later. Only the prefix will be visible."
    }

@router.delete("/{key_id}")
async def revoke_key(
    key_id: str,
    current_user: dict = Depends(require_role("admin"))
):
    """Revoke (deactivate) an API key (admin only)"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Check if key exists and belongs to company
        cur.execute(
            "SELECT id, name, is_active FROM api_keys WHERE id = %s AND company_id = %s",
            (key_id, current_user["company_id"])
        )
        key = cur.fetchone()
        
        if not key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found"
            )
        
        if not key["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="API key is already revoked"
            )
        
        # Revoke key
        cur.execute(
            "UPDATE api_keys SET is_active = false WHERE id = %s",
            (key_id,)
        )
        conn.commit()
    
    return {
        "message": f"API key '{key['name']}' revoked successfully"
    }

@router.put("/{key_id}/activate")
async def activate_key(
    key_id: str,
    current_user: dict = Depends(require_role("admin"))
):
    """Reactivate a revoked API key (admin only)"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Check if key exists
        cur.execute(
            "SELECT id, name, is_active, expires_at FROM api_keys WHERE id = %s AND company_id = %s",
            (key_id, current_user["company_id"])
        )
        key = cur.fetchone()
        
        if not key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found"
            )
        
        if key["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="API key is already active"
            )
        
        # Check if expired
        if key["expires_at"] and key["expires_at"] < datetime.now():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot activate expired key. Create a new one."
            )
        
        # Activate key
        cur.execute(
            "UPDATE api_keys SET is_active = true WHERE id = %s",
            (key_id,)
        )
        conn.commit()
    
    return {
        "message": f"API key '{key['name']}' activated successfully"
    }

@router.get("/{key_id}/usage")
async def get_key_usage(
    key_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get usage statistics for a specific API key"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Verify key belongs to company
        cur.execute(
            "SELECT id, name FROM api_keys WHERE id = %s AND company_id = %s",
            (key_id, current_user["company_id"])
        )
        key = cur.fetchone()
        
        if not key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found"
            )
        
        # Get usage stats
        cur.execute("""
            SELECT 
                COUNT(*) as total_requests,
                SUM(input_tokens) as total_input_tokens,
                SUM(output_tokens) as total_output_tokens,
                SUM(total_cost_usd) as total_cost,
                AVG(latency_ms) as avg_latency_ms,
                MAX(created_at) as last_used
            FROM usage_logs
            WHERE api_key_id = %s
        """, (key_id,))
        stats = dict(cur.fetchone())
        
        # Get usage by endpoint
        cur.execute("""
            SELECT endpoint, COUNT(*) as count
            FROM usage_logs
            WHERE api_key_id = %s
            GROUP BY endpoint
            ORDER BY count DESC
        """, (key_id,))
        by_endpoint = [{"endpoint": r["endpoint"], "count": r["count"]} for r in cur.fetchall()]
    
    return {
        "key_name": key["name"],
        "usage": {
            "total_requests": stats["total_requests"] or 0,
            "total_input_tokens": stats["total_input_tokens"] or 0,
            "total_output_tokens": stats["total_output_tokens"] or 0,
            "total_cost_usd": float(stats["total_cost"] or 0),
            "avg_latency_ms": float(stats["avg_latency_ms"] or 0),
            "last_used": stats["last_used"].isoformat() if stats["last_used"] else None
        },
        "by_endpoint": by_endpoint
    }
