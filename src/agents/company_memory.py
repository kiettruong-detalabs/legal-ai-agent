"""
Company Memory — persistent context for each company.
Like OpenClaw's MEMORY.md but per-company in the database.

Builds a concise memory string from:
- Company profile
- Recent chat sessions
- Contracts summary
- Documents summary
- Custom memory notes (stored in company metadata)
"""
import json
from datetime import date, datetime
from psycopg2.extras import RealDictCursor

# Injected by init
_get_db = None


def init_memory(get_db_fn):
    """Initialize with shared DB function"""
    global _get_db
    _get_db = get_db_fn


async def get_company_memory(company_id: str) -> str:
    """
    Fetch company memory summary for AI context injection.
    Returns a concise Vietnamese string ready for system prompt.
    """
    if not _get_db:
        return ""

    parts = []

    try:
        with _get_db() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # 1. Company profile
            # Try with metadata column first, fall back without it
            try:
                cur.execute("""
                    SELECT name, plan, metadata
                    FROM companies WHERE id = %s
                """, (company_id,))
            except Exception:
                conn.rollback()
                cur.execute("""
                    SELECT name, plan
                    FROM companies WHERE id = %s
                """, (company_id,))
            company = cur.fetchone()
            if company:
                parts.append(f"- Tên: {company['name']}")
                # Parse metadata for custom notes (if column exists)
                metadata = company.get("metadata")
                if metadata:
                    if isinstance(metadata, str):
                        try:
                            metadata = json.loads(metadata)
                        except:
                            metadata = {}
                    if isinstance(metadata, dict):
                        if metadata.get("industry"):
                            parts.append(f"- Ngành: {metadata['industry']}")
                        if metadata.get("notes"):
                            parts.append(f"- Ghi chú: {metadata['notes']}")
                        if metadata.get("memory"):
                            for k, v in metadata["memory"].items():
                                parts.append(f"- {k}: {v}")

            # 2. Contracts summary
            cur.execute("""
                SELECT id, name, contract_type, status, end_date, parties
                FROM contracts
                WHERE company_id = %s AND status != 'deleted'
                ORDER BY created_at DESC
                LIMIT 10
            """, (company_id,))
            contracts = cur.fetchall()
            if contracts:
                active = [c for c in contracts if c.get("status") == "active"]
                expired = [c for c in contracts if c.get("status") == "expired"]
                
                contract_lines = []
                for c in contracts[:5]:
                    name = c.get("name", "N/A")
                    end = c.get("end_date")
                    status_str = ""
                    if end:
                        if isinstance(end, (date, datetime)):
                            days = (end - date.today()).days if isinstance(end, date) else (end.date() - date.today()).days
                            if days < 0:
                                status_str = f", đã hết hạn {abs(days)} ngày"
                            elif days <= 30:
                                status_str = f", sắp hết hạn ({days} ngày)"
                            else:
                                status_str = f", hết hạn {end}"
                    
                    parties_str = ""
                    if c.get("parties"):
                        try:
                            p = json.loads(c["parties"]) if isinstance(c["parties"], str) else c["parties"]
                            if isinstance(p, list) and p:
                                party_names = []
                                for party in p:
                                    if isinstance(party, dict):
                                        party_names.append(party.get("name", str(party)))
                                    else:
                                        party_names.append(str(party))
                                parties_str = f" với {', '.join(party_names[:2])}"
                        except:
                            pass
                    
                    contract_lines.append(f"  • {name}{parties_str}{status_str}")
                
                parts.append(f"- HĐ đang có: {len(active)} active, {len(expired)} expired (tổng {len(contracts)})")
                if contract_lines:
                    parts.extend(contract_lines)

            # 3. Documents summary
            cur.execute("""
                SELECT COUNT(*) as total, COUNT(DISTINCT doc_type) as types
                FROM documents WHERE company_id = %s
            """, (company_id,))
            doc_stats = cur.fetchone()
            if doc_stats and doc_stats["total"] > 0:
                parts.append(f"- Tài liệu: {doc_stats['total']} files ({doc_stats['types']} loại)")

            # 4. Recent chat topics (last 5 sessions)
            cur.execute("""
                SELECT title, last_message_at
                FROM chat_sessions
                WHERE company_id = %s AND status = 'active'
                ORDER BY last_message_at DESC NULLS LAST
                LIMIT 5
            """, (company_id,))
            sessions = cur.fetchall()
            if sessions:
                recent_topics = []
                for s in sessions[:3]:
                    title = s.get("title", "")
                    if title and len(title) > 10:
                        # Clean up auto-generated titles
                        clean = title.replace("Q&A - ", "").rstrip(".")
                        if len(clean) > 60:
                            clean = clean[:60] + "..."
                        recent_topics.append(clean)
                if recent_topics:
                    parts.append(f"- Chủ đề chat gần đây: {'; '.join(recent_topics)}")

    except Exception as e:
        # Don't break the agent if memory fetch fails
        print(f"Error fetching company memory: {e}")
        return ""

    if not parts:
        return ""

    return "## Bộ nhớ công ty:\n" + "\n".join(parts)


async def update_company_memory(company_id: str, key: str, value: str):
    """
    Update a specific memory entry in company metadata.
    Stores in metadata.memory dict.
    """
    if not _get_db:
        return

    try:
        with _get_db() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Get current metadata (column may not exist)
            try:
                cur.execute("SELECT metadata FROM companies WHERE id = %s", (company_id,))
            except Exception:
                conn.rollback()
                print("Company memory update skipped: metadata column not available")
                return

            row = cur.fetchone()
            if not row:
                return

            metadata = row.get("metadata") or {}
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}

            if not isinstance(metadata, dict):
                metadata = {}

            # Update memory section
            if "memory" not in metadata:
                metadata["memory"] = {}
            metadata["memory"][key] = value

            cur.execute(
                "UPDATE companies SET metadata = %s WHERE id = %s",
                (json.dumps(metadata, ensure_ascii=False), company_id)
            )
            conn.commit()
    except Exception as e:
        print(f"Error updating company memory: {e}")
