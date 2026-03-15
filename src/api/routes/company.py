"""
Company management endpoints
- Get/update company info
- Manage members
- Invite system
"""
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from psycopg2.extras import RealDictCursor
import secrets
from datetime import datetime, timedelta

from ..middleware.auth import get_db, get_current_user, require_role

router = APIRouter(prefix="/v1/company", tags=["Company"])

# ============================================
# Models
# ============================================

class UpdateCompanyRequest(BaseModel):
    name: Optional[str] = None
    industry: Optional[str] = None
    employee_count: Optional[int] = None
    tax_code: Optional[str] = None
    billing_email: Optional[EmailStr] = None
    billing_address: Optional[str] = None
    settings: Optional[dict] = None

class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str = "member"  # owner, admin, member, viewer

# ============================================
# Endpoints
# ============================================

@router.get("")
async def get_company(current_user: dict = Depends(get_current_user)):
    """Get company information"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, name, slug, plan, monthly_quota, used_quota, quota_reset_at,
                   settings, industry, employee_count, tax_code, billing_email, 
                   billing_address, subscription_status, trial_ends_at, created_at
            FROM companies
            WHERE id = %s
        """, (current_user["company_id"],))
        company = cur.fetchone()
        
        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found"
            )
        
        # Get member count
        cur.execute(
            "SELECT COUNT(*) as member_count FROM users WHERE company_id = %s AND is_active = true",
            (current_user["company_id"],)
        )
        member_count = cur.fetchone()["member_count"]
        
        # Get API key count
        cur.execute(
            "SELECT COUNT(*) as key_count FROM api_keys WHERE company_id = %s AND is_active = true",
            (current_user["company_id"],)
        )
        key_count = cur.fetchone()["key_count"]
        
        return {
            "id": str(company["id"]),
            "name": company["name"],
            "slug": company["slug"],
            "plan": company["plan"],
            "quota": {
                "monthly_limit": company["monthly_quota"],
                "used": company["used_quota"],
                "remaining": company["monthly_quota"] - company["used_quota"],
                "reset_at": company["quota_reset_at"].isoformat() if company["quota_reset_at"] else None
            },
            "subscription": {
                "status": company["subscription_status"],
                "trial_ends_at": company["trial_ends_at"].isoformat() if company["trial_ends_at"] else None
            },
            "settings": company["settings"],
            "industry": company["industry"],
            "employee_count": company["employee_count"],
            "tax_code": company["tax_code"],
            "billing_email": company["billing_email"],
            "billing_address": company["billing_address"],
            "stats": {
                "members": member_count,
                "api_keys": key_count
            },
            "created_at": company["created_at"].isoformat()
        }

@router.put("")
async def update_company(
    data: UpdateCompanyRequest,
    current_user: dict = Depends(require_role("admin"))
):
    """Update company information (admin only)"""
    update_fields = []
    params = []
    
    if data.name:
        update_fields.append("name = %s")
        params.append(data.name)
    if data.industry:
        update_fields.append("industry = %s")
        params.append(data.industry)
    if data.employee_count is not None:
        update_fields.append("employee_count = %s")
        params.append(data.employee_count)
    if data.tax_code:
        update_fields.append("tax_code = %s")
        params.append(data.tax_code)
    if data.billing_email:
        update_fields.append("billing_email = %s")
        params.append(data.billing_email)
    if data.billing_address:
        update_fields.append("billing_address = %s")
        params.append(data.billing_address)
    if data.settings:
        update_fields.append("settings = %s")
        params.append(data.settings)
    
    if not update_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update"
        )
    
    params.append(current_user["company_id"])
    
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        query = f"UPDATE companies SET {', '.join(update_fields)}, updated_at = now() WHERE id = %s RETURNING *"
        cur.execute(query, params)
        updated_company = dict(cur.fetchone())
        conn.commit()
    
    return {
        "message": "Company updated successfully",
        "company": {
            "id": str(updated_company["id"]),
            "name": updated_company["name"],
            "industry": updated_company["industry"],
            "employee_count": updated_company["employee_count"]
        }
    }

@router.get("/members")
async def list_members(current_user: dict = Depends(get_current_user)):
    """List company members"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, role, full_name, email, avatar_url, 
                   is_active, last_login_at, created_at
            FROM users
            WHERE company_id = %s
            ORDER BY created_at ASC
        """, (current_user["company_id"],))
        members = cur.fetchall()
    
    return {
        "members": [{
            "id": str(m["id"]),
            "full_name": m["full_name"],
            "email": m["email"],
            "role": m["role"],
            "avatar_url": m["avatar_url"],
            "is_active": m["is_active"],
            "last_login_at": m["last_login_at"].isoformat() if m["last_login_at"] else None,
            "joined_at": m["created_at"].isoformat()
        } for m in members]
    }

@router.post("/invite")
async def invite_member(
    data: InviteMemberRequest,
    current_user: dict = Depends(require_role("admin"))
):
    """Invite a new member to the company (admin only)"""
    # Validate role
    valid_roles = ["owner", "admin", "member", "viewer"]
    if data.role not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}"
        )
    
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Check if user already exists in company
        cur.execute(
            "SELECT id FROM users WHERE email = %s AND company_id = %s",
            (data.email, current_user["company_id"])
        )
        if cur.fetchone():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User already exists in this company"
            )
        
        # Check for existing pending invite
        cur.execute("""
            SELECT id FROM company_invites 
            WHERE email = %s AND company_id = %s AND accepted_at IS NULL AND expires_at > now()
        """, (data.email, current_user["company_id"]))
        existing_invite = cur.fetchone()
        
        if existing_invite:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Pending invitation already exists for this email"
            )
        
        # Create invitation
        invite_token = secrets.token_urlsafe(32)
        cur.execute("""
            INSERT INTO company_invites (company_id, inviter_id, email, role, token, expires_at)
            VALUES (%s, %s, %s, %s::user_role, %s, now() + interval '7 days')
            RETURNING id, token, expires_at
        """, (current_user["company_id"], current_user["id"], data.email, data.role, invite_token))
        invite = dict(cur.fetchone())
        conn.commit()
        
        # In production, send email here
        invite_url = f"https://your-app.com/accept-invite?token={invite['token']}"
        
        return {
            "message": "Invitation sent successfully",
            "invite": {
                "id": str(invite["id"]),
                "email": data.email,
                "role": data.role,
                "invite_url": invite_url,
                "expires_at": invite["expires_at"].isoformat()
            },
            "note": "In production, this would send an email. For now, share the invite_url manually."
        }

@router.delete("/members/{user_id}")
async def remove_member(
    user_id: str,
    current_user: dict = Depends(require_role("admin"))
):
    """Remove a member from the company (admin only)"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Check if user exists in company
        cur.execute(
            "SELECT id, role, email FROM users WHERE id = %s AND company_id = %s",
            (user_id, current_user["company_id"])
        )
        user_to_remove = cur.fetchone()
        
        if not user_to_remove:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found in this company"
            )
        
        # Prevent removing yourself
        if str(user_to_remove["id"]) == str(current_user["id"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot remove yourself"
            )
        
        # Prevent removing the owner (unless you are the owner)
        if user_to_remove["role"] == "owner" and current_user["role"] != "owner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owner can remove the owner"
            )
        
        # Deactivate user instead of deleting (preserve data integrity)
        cur.execute(
            "UPDATE users SET is_active = false, updated_at = now() WHERE id = %s",
            (user_id,)
        )
        conn.commit()
    
    return {
        "message": f"User {user_to_remove['email']} removed successfully"
    }

@router.get("/invites")
async def list_invites(current_user: dict = Depends(get_current_user)):
    """List pending invitations"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT ci.id, ci.email, ci.role, ci.token, ci.expires_at, ci.created_at,
                   u.full_name as inviter_name
            FROM company_invites ci
            LEFT JOIN users u ON u.id = ci.inviter_id
            WHERE ci.company_id = %s AND ci.accepted_at IS NULL AND ci.expires_at > now()
            ORDER BY ci.created_at DESC
        """, (current_user["company_id"],))
        invites = cur.fetchall()
    
    return {
        "invites": [{
            "id": str(inv["id"]),
            "email": inv["email"],
            "role": inv["role"],
            "inviter_name": inv["inviter_name"],
            "expires_at": inv["expires_at"].isoformat(),
            "created_at": inv["created_at"].isoformat()
        } for inv in invites]
    }
