"""
Chat history management endpoints
- List chat sessions
- Get chat with messages
- Delete chat
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List
from psycopg2.extras import RealDictCursor

from ..middleware.auth import get_db, get_current_user

router = APIRouter(prefix="/v1/chats", tags=["Chat History"])

# ============================================
# Models
# ============================================

class UpdateChatRequest(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None

# ============================================
# Endpoints
# ============================================

@router.get("")
async def list_chats(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    agent_type: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """List chat sessions for the company"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Build query
        base_query = """
            SELECT 
                cs.id, cs.title, cs.agent_type, cs.status, cs.message_count,
                cs.last_message_at, cs.created_at,
                u.full_name as created_by_name
            FROM chat_sessions cs
            LEFT JOIN users u ON u.id = cs.user_id
            WHERE cs.company_id = %s
        """
        params = [current_user["company_id"]]
        
        if agent_type:
            base_query += " AND cs.agent_type = %s::agent_type"
            params.append(agent_type)
        
        base_query += " ORDER BY cs.last_message_at DESC NULLS LAST, cs.created_at DESC"
        base_query += " LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        cur.execute(base_query, params)
        sessions = cur.fetchall()
        
        # Get total count
        count_query = "SELECT COUNT(*) FROM chat_sessions WHERE company_id = %s"
        count_params = [current_user["company_id"]]
        if agent_type:
            count_query += " AND agent_type = %s::agent_type"
            count_params.append(agent_type)
        
        cur.execute(count_query, count_params)
        total = cur.fetchone()["count"]
    
    return {
        "chats": [
            {
                "id": str(s["id"]),
                "title": s["title"] or "Untitled Chat",
                "agent_type": s["agent_type"],
                "status": s["status"],
                "message_count": s["message_count"] or 0,
                "created_by": s["created_by_name"],
                "last_message_at": s["last_message_at"].isoformat() if s["last_message_at"] else None,
                "created_at": s["created_at"].isoformat()
            }
            for s in sessions
        ],
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + limit) < total
        }
    }

@router.get("/{session_id}")
async def get_chat(
    session_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get chat session with all messages"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get session
        cur.execute("""
            SELECT 
                cs.id, cs.title, cs.agent_type, cs.status, cs.metadata,
                cs.message_count, cs.last_message_at, cs.created_at,
                u.full_name as created_by_name, u.email as created_by_email
            FROM chat_sessions cs
            LEFT JOIN users u ON u.id = cs.user_id
            WHERE cs.id = %s AND cs.company_id = %s
        """, (session_id, current_user["company_id"]))
        session = cur.fetchone()
        
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")
        
        # Get messages
        cur.execute("""
            SELECT 
                id, role, content, citations, confidence, tokens_used,
                model, feedback, feedback_note, metadata, created_at
            FROM messages
            WHERE session_id = %s
            ORDER BY created_at ASC
        """, (session_id,))
        messages = cur.fetchall()
    
    return {
        "session": {
            "id": str(session["id"]),
            "title": session["title"] or "Untitled Chat",
            "agent_type": session["agent_type"],
            "status": session["status"],
            "metadata": session["metadata"],
            "message_count": session["message_count"] or 0,
            "created_by": {
                "name": session["created_by_name"],
                "email": session["created_by_email"]
            },
            "last_message_at": session["last_message_at"].isoformat() if session["last_message_at"] else None,
            "created_at": session["created_at"].isoformat()
        },
        "messages": [
            {
                "id": str(m["id"]),
                "role": m["role"],
                "content": m["content"],
                "citations": m["citations"] or [],
                "confidence": m["confidence"],
                "tokens_used": m["tokens_used"],
                "model": m["model"],
                "feedback": m["feedback"],
                "feedback_note": m["feedback_note"],
                "metadata": m["metadata"],
                "created_at": m["created_at"].isoformat()
            }
            for m in messages
        ]
    }

@router.put("/{session_id}")
async def update_chat(
    session_id: str,
    data: UpdateChatRequest,
    current_user: dict = Depends(get_current_user)
):
    """Update chat session (e.g., rename title)"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Verify ownership
        cur.execute(
            "SELECT id FROM chat_sessions WHERE id = %s AND company_id = %s",
            (session_id, current_user["company_id"])
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Chat session not found")
        
        # Build update query
        update_fields = []
        params = []
        
        if data.title is not None:
            update_fields.append("title = %s")
            params.append(data.title)
        if data.status is not None:
            update_fields.append("status = %s")
            params.append(data.status)
        
        if not update_fields:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        params.append(session_id)
        query = f"UPDATE chat_sessions SET {', '.join(update_fields)} WHERE id = %s RETURNING *"
        
        cur.execute(query, params)
        updated_session = dict(cur.fetchone())
        conn.commit()
    
    return {
        "message": "Chat updated successfully",
        "session": {
            "id": str(updated_session["id"]),
            "title": updated_session["title"],
            "status": updated_session["status"]
        }
    }

@router.delete("/{session_id}")
async def delete_chat(
    session_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a chat session and all its messages"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Verify ownership
        cur.execute(
            "SELECT id, title FROM chat_sessions WHERE id = %s AND company_id = %s",
            (session_id, current_user["company_id"])
        )
        session = cur.fetchone()
        
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")
        
        # Delete session (messages will cascade delete)
        cur.execute("DELETE FROM chat_sessions WHERE id = %s", (session_id,))
        conn.commit()
    
    return {
        "message": f"Chat '{session['title'] or 'Untitled'}' deleted successfully"
    }

@router.get("/{session_id}/export")
async def export_chat(
    session_id: str,
    format: str = Query("json", pattern="^(json|txt|md)$"),
    current_user: dict = Depends(get_current_user)
):
    """Export chat to different formats"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get session
        cur.execute("""
            SELECT cs.id, cs.title, cs.agent_type, cs.created_at,
                   u.full_name as created_by
            FROM chat_sessions cs
            LEFT JOIN users u ON u.id = cs.user_id
            WHERE cs.id = %s AND cs.company_id = %s
        """, (session_id, current_user["company_id"]))
        session = cur.fetchone()
        
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")
        
        # Get messages
        cur.execute("""
            SELECT role, content, created_at
            FROM messages
            WHERE session_id = %s
            ORDER BY created_at ASC
        """, (session_id,))
        messages = cur.fetchall()
    
    if format == "json":
        return {
            "session": {
                "id": str(session["id"]),
                "title": session["title"],
                "agent_type": session["agent_type"],
                "created_by": session["created_by"],
                "created_at": session["created_at"].isoformat()
            },
            "messages": [
                {
                    "role": m["role"],
                    "content": m["content"],
                    "timestamp": m["created_at"].isoformat()
                }
                for m in messages
            ]
        }
    
    elif format == "md":
        lines = [
            f"# {session['title'] or 'Chat Export'}",
            f"**Agent Type:** {session['agent_type']}",
            f"**Created:** {session['created_at'].strftime('%Y-%m-%d %H:%M')}",
            f"**Created By:** {session['created_by'] or 'Unknown'}",
            "",
            "---",
            ""
        ]
        
        for msg in messages:
            role_emoji = "👤" if msg["role"] == "user" else "🤖"
            lines.append(f"### {role_emoji} {msg['role'].title()}")
            lines.append(f"*{msg['created_at'].strftime('%Y-%m-%d %H:%M:%S')}*")
            lines.append("")
            lines.append(msg["content"])
            lines.append("")
            lines.append("---")
            lines.append("")
        
        return {"content": "\n".join(lines), "format": "markdown"}
    
    else:  # txt
        lines = [
            f"Chat: {session['title'] or 'Untitled'}",
            f"Agent: {session['agent_type']}",
            f"Date: {session['created_at'].strftime('%Y-%m-%d %H:%M')}",
            f"Created by: {session['created_by'] or 'Unknown'}",
            "",
            "=" * 60,
            ""
        ]
        
        for msg in messages:
            lines.append(f"[{msg['created_at'].strftime('%H:%M:%S')}] {msg['role'].upper()}:")
            lines.append(msg["content"])
            lines.append("")
            lines.append("-" * 60)
            lines.append("")
        
        return {"content": "\n".join(lines), "format": "text"}
