"""
Document management endpoints
- Upload, list, get, delete documents
"""
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Query
from pydantic import BaseModel
from typing import Optional, List
from psycopg2.extras import RealDictCursor
import os
import uuid
from pathlib import Path

from ..middleware.auth import get_db, get_current_user, require_role

router = APIRouter(prefix="/v1/documents", tags=["Documents"])

# Configuration
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/home/admin_1/projects/legal-ai-agent/uploads"))
UPLOAD_DIR.mkdir(exist_ok=True, parents=True)
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

# ============================================
# Models
# ============================================

class UpdateDocumentRequest(BaseModel):
    name: Optional[str] = None
    doc_type: Optional[str] = None
    status: Optional[str] = None

# ============================================
# Helper Functions
# ============================================

def save_upload_file(upload_file: UploadFile, company_id: str) -> tuple[str, int]:
    """Save uploaded file and return (file_path, file_size)"""
    # Create company directory
    company_dir = UPLOAD_DIR / company_id
    company_dir.mkdir(exist_ok=True, parents=True)
    
    # Generate unique filename
    file_ext = Path(upload_file.filename).suffix
    unique_name = f"{uuid.uuid4()}{file_ext}"
    file_path = company_dir / unique_name
    
    # Save file
    file_size = 0
    with open(file_path, "wb") as f:
        while chunk := upload_file.file.read(8192):
            file_size += len(chunk)
            if file_size > MAX_FILE_SIZE:
                file_path.unlink()  # Delete partial file
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum size: {MAX_FILE_SIZE / 1024 / 1024}MB"
                )
            f.write(chunk)
    
    return str(file_path.relative_to(UPLOAD_DIR)), file_size

# ============================================
# Endpoints
# ============================================

@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    doc_type: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Upload a document"""
    # Validate file type
    allowed_types = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain"
    ]
    
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"File type not supported. Allowed: PDF, DOC, DOCX, TXT"
        )
    
    try:
        # Save file
        file_path, file_size = save_upload_file(file, str(current_user["company_id"]))
        
        # Insert into database
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            cur.execute("""
                INSERT INTO documents 
                (company_id, uploaded_by, name, file_path, file_size, mime_type, doc_type, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s::doc_type, 'uploaded'::doc_status)
                RETURNING id, name, file_path, file_size, mime_type, doc_type, status, created_at
            """, (
                current_user["company_id"],
                current_user["id"],
                file.filename,
                file_path,
                file_size,
                file.content_type,
                doc_type
            ))
            
            document = dict(cur.fetchone())
            conn.commit()
        
        return {
            "message": "Document uploaded successfully",
            "document": {
                "id": str(document["id"]),
                "name": document["name"],
                "file_size": document["file_size"],
                "mime_type": document["mime_type"],
                "doc_type": document["doc_type"],
                "status": document["status"],
                "created_at": document["created_at"].isoformat()
            }
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@router.get("")
async def list_documents(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    doc_type: Optional[str] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """List documents for the company"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Build query
        base_query = """
            SELECT 
                d.id, d.name, d.file_size, d.mime_type, d.doc_type, d.status,
                d.page_count, d.risk_score, d.issues_count, d.created_at, d.analyzed_at,
                u.full_name as uploaded_by_name
            FROM documents d
            LEFT JOIN users u ON u.id = d.uploaded_by
            WHERE d.company_id = %s
        """
        params = [current_user["company_id"]]
        
        if doc_type:
            base_query += " AND d.doc_type = %s::doc_type"
            params.append(doc_type)
        
        if status:
            base_query += " AND d.status = %s::doc_status"
            params.append(status)
        
        base_query += " ORDER BY d.created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        cur.execute(base_query, params)
        documents = cur.fetchall()
        
        # Get total count
        count_query = "SELECT COUNT(*) FROM documents WHERE company_id = %s"
        count_params = [current_user["company_id"]]
        if doc_type:
            count_query += " AND doc_type = %s::doc_type"
            count_params.append(doc_type)
        if status:
            count_query += " AND status = %s::doc_status"
            count_params.append(status)
        
        cur.execute(count_query, count_params)
        total = cur.fetchone()["count"]
    
    return {
        "documents": [
            {
                "id": str(d["id"]),
                "name": d["name"],
                "file_size": d["file_size"],
                "mime_type": d["mime_type"],
                "doc_type": d["doc_type"],
                "status": d["status"],
                "page_count": d["page_count"],
                "risk_score": d["risk_score"],
                "issues_count": d["issues_count"],
                "uploaded_by": d["uploaded_by_name"],
                "created_at": d["created_at"].isoformat(),
                "analyzed_at": d["analyzed_at"].isoformat() if d["analyzed_at"] else None
            }
            for d in documents
        ],
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + limit) < total
        }
    }

@router.get("/{document_id}")
async def get_document(
    document_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get document details"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT 
                d.id, d.name, d.file_path, d.file_size, d.mime_type, d.doc_type,
                d.status, d.extracted_text, d.page_count, d.analysis, d.risk_score,
                d.issues_count, d.created_at, d.analyzed_at,
                u.full_name as uploaded_by_name, u.email as uploaded_by_email
            FROM documents d
            LEFT JOIN users u ON u.id = d.uploaded_by
            WHERE d.id = %s AND d.company_id = %s
        """, (document_id, current_user["company_id"]))
        
        document = cur.fetchone()
        
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
    
    return {
        "id": str(document["id"]),
        "name": document["name"],
        "file_size": document["file_size"],
        "mime_type": document["mime_type"],
        "doc_type": document["doc_type"],
        "status": document["status"],
        "page_count": document["page_count"],
        "extracted_text": document["extracted_text"][:1000] if document["extracted_text"] else None,  # Preview only
        "analysis": document["analysis"],
        "risk_score": document["risk_score"],
        "issues_count": document["issues_count"],
        "uploaded_by": {
            "name": document["uploaded_by_name"],
            "email": document["uploaded_by_email"]
        },
        "created_at": document["created_at"].isoformat(),
        "analyzed_at": document["analyzed_at"].isoformat() if document["analyzed_at"] else None
    }

@router.put("/{document_id}")
async def update_document(
    document_id: str,
    data: UpdateDocumentRequest,
    current_user: dict = Depends(get_current_user)
):
    """Update document metadata"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Verify ownership
        cur.execute(
            "SELECT id FROM documents WHERE id = %s AND company_id = %s",
            (document_id, current_user["company_id"])
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Build update query
        update_fields = []
        params = []
        
        if data.name:
            update_fields.append("name = %s")
            params.append(data.name)
        if data.doc_type:
            update_fields.append("doc_type = %s::doc_type")
            params.append(data.doc_type)
        if data.status:
            update_fields.append("status = %s::doc_status")
            params.append(data.status)
        
        if not update_fields:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        params.append(document_id)
        query = f"UPDATE documents SET {', '.join(update_fields)} WHERE id = %s RETURNING *"
        
        cur.execute(query, params)
        updated_doc = dict(cur.fetchone())
        conn.commit()
    
    return {
        "message": "Document updated successfully",
        "document": {
            "id": str(updated_doc["id"]),
            "name": updated_doc["name"],
            "doc_type": updated_doc["doc_type"],
            "status": updated_doc["status"]
        }
    }

@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a document"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get document info
        cur.execute("""
            SELECT id, name, file_path
            FROM documents
            WHERE id = %s AND company_id = %s
        """, (document_id, current_user["company_id"]))
        
        document = cur.fetchone()
        
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Delete file from disk
        try:
            file_path = UPLOAD_DIR / document["file_path"]
            if file_path.exists():
                file_path.unlink()
        except Exception as e:
            print(f"Warning: Could not delete file {document['file_path']}: {e}")
        
        # Delete from database
        cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))
        conn.commit()
    
    return {
        "message": f"Document '{document['name']}' deleted successfully"
    }

@router.get("/{document_id}/download")
async def download_document(
    document_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get download URL for a document"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT id, name, file_path, mime_type
            FROM documents
            WHERE id = %s AND company_id = %s
        """, (document_id, current_user["company_id"]))
        
        document = cur.fetchone()
        
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        file_path = UPLOAD_DIR / document["file_path"]
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found on disk")
    
    # In production, you'd return a signed URL or use FileResponse
    return {
        "document_id": str(document["id"]),
        "name": document["name"],
        "download_url": f"/uploads/{document['file_path']}",  # Configure nginx/static serving
        "mime_type": document["mime_type"],
        "note": "In production, use signed URLs or direct file serving"
    }
