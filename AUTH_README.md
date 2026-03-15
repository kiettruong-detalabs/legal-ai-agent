# User Authentication & Management System

Complete authentication and management layer for Legal AI Agent (Vietnamese Legal SaaS).

## 🚀 Features Implemented

### ✅ 1. User Authentication
- **Register** (`POST /v1/auth/register`) - Create account + company + API key
- **Login** (`POST /v1/auth/login`) - Email/password authentication with JWT
- **Token Refresh** (`POST /v1/auth/refresh`) - Refresh access tokens
- **Profile Management** (`GET/PUT /v1/auth/me`) - View and update user profile
- **Change Password** (`POST /v1/auth/change-password`)
- **Logout** (`POST /v1/auth/logout`)

### ✅ 2. Company Management
- **Get Company** (`GET /v1/company`) - Company info + stats
- **Update Company** (`PUT /v1/company`) - Admin-only company settings
- **List Members** (`GET /v1/company/members`) - All company users
- **Invite Member** (`POST /v1/company/invite`) - Email invitations with roles
- **Remove Member** (`DELETE /v1/company/members/{id}`) - Deactivate users
- **List Invites** (`GET /v1/company/invites`) - Pending invitations

### ✅ 3. API Key Management
- **List Keys** (`GET /v1/keys`) - All API keys for company
- **Create Key** (`POST /v1/keys`) - Generate new API key (admin-only)
- **Revoke Key** (`DELETE /v1/keys/{id}`) - Deactivate API key
- **Activate Key** (`PUT /v1/keys/{id}/activate`) - Reactivate key
- **Key Usage Stats** (`GET /v1/keys/{id}/usage`) - Per-key analytics

### ✅ 4. Usage Tracking & Billing
- **Current Usage** (`GET /v1/usage`) - Monthly stats + quota tracking
- **Usage History** (`GET /v1/usage/history`) - Historical data by month
- **Endpoint Stats** (`GET /v1/usage/endpoints`) - Usage breakdown
- **Billing Info** (`GET /v1/billing`) - Subscription + invoices

### ✅ 5. Chat History
- **List Chats** (`GET /v1/chats`) - All chat sessions
- **Get Chat** (`GET /v1/chats/{id}`) - Full conversation with messages
- **Update Chat** (`PUT /v1/chats/{id}`) - Rename/update status
- **Delete Chat** (`DELETE /v1/chats/{id}`) - Remove session
- **Export Chat** (`GET /v1/chats/{id}/export?format=json|txt|md`) - Download

### ✅ 6. Document Management
- **Upload** (`POST /v1/documents`) - PDF, DOCX, TXT files
- **List** (`GET /v1/documents`) - All company documents
- **Get** (`GET /v1/documents/{id}`) - Document details + analysis
- **Update** (`PUT /v1/documents/{id}`) - Metadata updates
- **Delete** (`DELETE /v1/documents/{id}`) - Remove document
- **Download** (`GET /v1/documents/{id}/download`) - File download

## 🔐 Security Features

### JWT Authentication
- HS256 signed tokens
- Access tokens (60 min expiry)
- Refresh tokens (30 days expiry)
- Secure password hashing with bcrypt

### Multi-Tenant Isolation
- Row-Level Security (RLS) policies on all tables
- Company-scoped data access
- Role-based permissions (owner > admin > member > viewer)

### API Key Authentication
- SHA256 hashed keys
- Rate limiting per key
- Granular permissions
- Key expiration support

## 📊 Database Changes

### New Tables
- `company_invites` - Member invitation system

### Updated Tables
- `users` - Added: auth_id, password_hash, user_settings, last_login_at, is_active
- `companies` - Added: billing fields, subscription status, trial info

### RLS Policies
All tenant-specific tables now have Row-Level Security enabled with company-scoped policies.

## 🛠️ Setup & Installation

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Migration
```bash
python3 scripts/run_migration.py
```

### 3. Set Environment Variables
Add to `.env`:
```env
SUPABASE_JWT_SECRET=your-secret-key-here
```

### 4. Start Server
```bash
uvicorn src.api.main:app --reload --port 8080
```

### 5. Test Endpoints
```bash
python3 scripts/test_auth.py
```

## 📖 API Usage Examples

### Register New User
```bash
curl -X POST http://localhost:8080/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "SecurePass123",
    "full_name": "John Doe",
    "company_name": "ACME Corp"
  }'
```

Response:
```json
{
  "user": {...},
  "company": {...},
  "api_key": "lak_abc123...",
  "access_token": "eyJ...",
  "refresh_token": "eyJ..."
}
```

### Login
```bash
curl -X POST http://localhost:8080/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "SecurePass123"
  }'
```

### Get Current User (Protected Route)
```bash
curl http://localhost:8080/v1/auth/me \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Use API Key for Legal Endpoints
The existing `/v1/legal/*` endpoints still work with API key authentication:
```bash
curl http://localhost:8080/v1/legal/ask \
  -H "X-API-Key: lak_your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Quy định về thời gian thử việc?"
  }'
```

## 🔑 Authentication Methods

The API supports **two authentication methods**:

1. **JWT Bearer Tokens** (for user sessions)
   - Header: `Authorization: Bearer <access_token>`
   - Used for: User management, profile, company settings

2. **API Keys** (for service/app access)
   - Header: `X-API-Key: <api_key>`
   - Used for: Legal AI endpoints (/v1/legal/*)

## 👥 User Roles

| Role | Permissions |
|------|-------------|
| **owner** | Full access - can manage company, members, billing |
| **admin** | Manage members, API keys, settings |
| **member** | Use AI features, view chat history, upload docs |
| **viewer** | Read-only access |

## 📁 File Structure

```
src/api/
├── main.py                 # Main FastAPI app (updated)
├── middleware/
│   └── auth.py            # JWT & auth middleware
└── routes/
    ├── auth.py            # Authentication endpoints
    ├── company.py         # Company management
    ├── keys.py            # API key management
    ├── usage.py           # Usage tracking & billing
    ├── chats.py           # Chat history
    └── documents.py       # Document management

scripts/
├── migration_auth.sql     # Database migration
├── run_migration.py       # Migration runner
└── test_auth.py          # API tests
```

## ✅ Testing Results

All endpoints tested successfully:
- ✅ User registration with auto company creation
- ✅ Login with JWT token generation
- ✅ Profile management
- ✅ Company info retrieval
- ✅ API key listing
- ✅ Role-based access control
- ✅ Multi-tenant data isolation

## 🔄 Backward Compatibility

**All existing `/v1/legal/*` endpoints remain unchanged:**
- `/v1/legal/ask` - Legal Q&A
- `/v1/legal/review` - Contract review
- `/v1/legal/draft` - Document drafting
- `/v1/legal/search` - Law search

They continue to work with API key authentication.

## 🎯 Next Steps (Optional Enhancements)

- [ ] Email verification for new users
- [ ] Password reset flow
- [ ] Two-factor authentication (2FA)
- [ ] OAuth integration (Google, Microsoft)
- [ ] Webhook notifications
- [ ] Advanced analytics dashboard
- [ ] Team collaboration features
- [ ] Document version history

## 📝 Migration Notes

Run the migration to add:
- Auth fields to users table
- Company invites table
- Billing fields to companies
- RLS policies for multi-tenant isolation

```bash
python3 scripts/run_migration.py
```

Migration is idempotent - safe to run multiple times.

## 🐛 Troubleshooting

### "Token has expired"
Refresh the token using `/v1/auth/refresh` endpoint.

### "Invalid API key"
Check that:
1. Key is correctly formatted: `lak_...`
2. Key hasn't been revoked
3. Company hasn't exceeded quota

### "Insufficient permissions"
User role doesn't have required access level. Contact admin to upgrade role.

## 📞 Support

For issues or questions, contact the development team.

---

**Built with:** FastAPI, Supabase PostgreSQL, JWT, bcrypt
**Version:** 2.0.0
**Last Updated:** 2026-03-15
