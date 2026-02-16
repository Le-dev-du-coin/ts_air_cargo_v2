---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: ['_bmad-output/planning-artifacts/prd.md', '_bmad-output/planning-artifacts/product-brief-ts_air_cargo_v2-2026-02-06.md', '_bmad-output/planning-artifacts/ux-design-specification.md']
workflowType: 'architecture'
projectName: 'ts_air_cargo_v2'
date: '2026-02-10'
---

# Architecture Decision Record - ts_air_cargo_v2

<!-- Architecture decisions will be documented through collaborative workflow steps -->

## Project Context Analysis

### Requirements Overview

**Functional Requirements: 29 FRs organisés en 7 modules**

1. **Gestion Colis (Chine)** : Scan QR, capture photo webcam, pesée automatique, étiquetage
2. **Vols & Manifestes** : Groupage aérien, validation vols, génération manifestes PDF
3. **Distribution (Mali/RCI)** : Pointage arrivées, gestion stock, remise colis, encaissement
4. **Rapports** : PDF journaliers agents, rapports consolidés admins, analytics pays
5. **Notifications** : WhatsApp multi-étapes avec queue/retry, deep links sans login
6. **Tracking Client** : Portail web mobile, suivi temps réel, multi-langue
7. **Administration** : Dashboards role-specific, gestion utilisateurs RBAC, audit logs

**Non-Functional Requirements: 21 NFRs critiques**

- **Performance** : 
  - < 15 secondes traitement colis Agent Chine
  - < 3 secondes chargement dashboards
  - < 2 secondes tracking client mobile
- **Scalabilité** : 
  - 5000 colis/jour supportés
  - 100 utilisateurs concurrents
  - Croissance 200% prévue année 1
- **Sécurité** : 
  - Authentication JWT
  - HTTPS obligatoire
  - RBAC 7 rôles distincts
  - Audit logs toutes opérations financières
- **Accessibilité** : WCAG 2.1 Level AA compliance
- **Mobile** : PWA, responsive, offline-capable (IndexedDB)
- **Reliability** : 99.5% uptime, backups quotidiens, disaster recovery

### Scale & Complexity

**Primary Domain:** Full-Stack Web Application (Logistics)  
**Complexity Level:** **Medium-High**

**Complexity Indicators:**

- **Multi-Interface** : 7 interfaces utilisateur distinctes avec besoins UX différents
- **Multi-Tenancy** : 3 pays (Chine, Mali, Côte d'Ivoire) avec données isolées
- **Real-Time Requirements** : Dashboards live, notifications push instantanées
- **Hardware Integration** : Webcam (WebRTC), scanners QR, imprimantes thermiques
- **External Integrations** : WhatsApp Business API, potentiel Stripe payments
- **Offline-First** : Agents terrain doivent fonctionner sans connexion stable
- **Financial Rigor** : Zéro tolérance écarts caisse, audit trail complet

**Estimated Architectural Components:**

- Frontend : 7 interfaces (3 desktop agents, 3 dashboards admins, 1 portail client mobile)
- Backend : API REST/GraphQL, queue workers, notification service
- Database : Multi-tenant PostgreSQL, IndexedDB client-side
- Storage : File storage photos/PDFs (S3-compatible)
- Infrastructure : CDN, load balancer, queue system

### Technical Constraints & Dependencies

**UX Design Decisions (Contraintes établies):**

- **Platform Strategy** : Progressive Web App responsive (pas d'app native)
- **Design System** : Tailwind CSS + shadcn/ui (composants headless React)
- **Webcam Integration** : WebRTC/MediaDevices API browser natif
- **Offline Strategy** : IndexedDB avec synchronisation automatique background
- **Typography** : Inter (primary), JetBrains Mono (monospace codes)
- **Accessibility** : WCAG 2.1 AA (contrast, keyboard navigation, screen readers)

**Infrastructure Requirements:**

- Multi-tenant database architecture (row-level security ou schemas séparés)
- Message queue system pour notifications (retry logic, dead letter queues)
- Object storage pour photos colis et PDFs générés
- Real-time communication (WebSocket, Server-Sent Events, ou polling)
- Background job processing (manifestes PDF, rapports, notifications batch)

**Integration Dependencies:**

- WhatsApp Business API (notifications 4 étapes clés)
- Printing service (reçus, étiquettes QR, manifestes)
- Potentiel payment gateway (Stripe pour paiements en ligne clients)

### Cross-Cutting Concerns Identified

**1. Authentication & Authorization**
- Multi-tenant JWT tokens (claim pays + rôle)
- RBAC 7 rôles : Agent Chine, Agent Mali, Agent RCI, Admin Chine, Admin Mali, Admin RCI, Client
- Permissions granulaires par module (lecture/écriture/validation)
- Session management (remember me, logout all devices)

**2. Internationalization & Localization (I18n/L10n)**
- Français langue principale (Mali/Côte d'Ivoire)
- Support multi-langue futur (Bambara, Dioula potentiels)
- Formats dates/montants localisés (FCFA Mali/RCI, CNY Chine)
- Timezone handling (UTC+0 Chine, UTC+0 Mali/RCI)

**3. Audit & Compliance Logging**
- Audit trail complet opérations financières (encaissement, validation vols)
- Logs immutables (append-only, tamper-proof)
- Retention 7 ans minimum (compliance fiscale)
- Exportation rapports audit (PDF, CSV)

**4. Data Synchronization (Offline-First)**
- Agents terrain peuvent perdre connexion 3G/4G
- Queue locale (IndexedDB) avec sync background
- Conflict resolution strategy (last-write-wins ou manual merge)
- Optimistic UI updates (feedback immédiat)

**5. Error Handling & Resilience**
- Notification queue avec retry exponentiel backoff
- Circuit breaker pattern intégrations externes (WhatsApp API)
- Graceful degradation (dashboards statiques si real-time échoue)
- User-friendly error messages (pas de stack traces exposés)

**6. Performance Monitoring & Observability**
- Dashboard latence API endpoints
- Webhook health monitoring (WhatsApp delivery rate)
- Photo upload success rate
- Database query performance (slow query log)
- Real-user monitoring (RUM) portail client mobile

## Starter Template Evaluation

### Primary Technology Domain

**Full-Stack Web Application (Logistics) - Decoupled Architecture**

**Domain Identification:**
- Backend API-first architecture (Django REST API)
- Frontend PWA multi-interface (React)
- Real-time capabilities (WebSocket dashboards)
- Background processing (Celery workers)
- Multi-tenant data isolation

**Technology Preference Context:**
- Developer expertise: **Python** (Django preferred)
- UX Design constraints: **React + Tailwind CSS + shadcn/ui**
- Performance requirements: High-throughput API (< 15s response time)
- Offline-first: IndexedDB client-side sync

### Starter Options Considered

**Option 1: Cookiecutter Django + Django Ninja (SELECTED)**
- **Backend:** Django 5.2 + Django Ninja API framework
- **Rationale:** Production-ready Django template with modern API layer
- **Performance:** Django Ninja 20-30% faster than DRF, type hints, async support
- **Latest Version:** cookiecutter-django 2026.01.20 (Django 5.2, Python 3.13)

**Option 2: Django REST Framework (DRF) - NOT SELECTED**
- **Reason:** Older architecture, slower than Django Ninja, no native async
- **Trade-off:** More mature ecosystem but verbose syntax, performance bottleneck

**Option 3: FastAPI Standalone - NOT SELECTED**
- **Reason:** Performance excellent but loses Django ORM, Admin, ecosystem
- **Trade-off:** Would require SQLAlchemy (learning curve), separate admin interface

**Frontend Options Considered:**

**Option A: Vite + React (SELECTED)**
- **Rationale:** Decoupled architecture, PWA-ready, ultra-fast builds
- **Latest:** Vite 6, React 19, Tailwind v4, shadcn@3.8.4

**Option B: Next.js 15 - NOT SELECTED**
- **Reason:** SSR/API routes unnecessary (backend API separate)
- **Trade-off:** Overhead for features not needed in decoupled architecture

### Selected Architecture: Django 5.2 + Django Ninja (Backend) + Vite + React (Frontend)

**Rationale for Decoupled Architecture:**

1. **Scalability:** Frontend CDN distribution, backend horizontal scaling independent
2. **Developer Expertise:** Python backend (user's strength), React frontend (industry standard)
3. **Deployment Flexibility:** Backend VPS Hostinger, Frontend Vercel/Netlify/CDN or VPS static
4. **API Reusability:** Future mobile app (React Native) can consume same API
5. **Performance:** Static assets CDN-cached, API optimized separately

---

### Backend Stack: Django 5.2 + Django Ninja (Manual Setup)

**Initialization Commands (Manual - Poetry):**

```bash
# Step 1: Create project directory
mkdir ts-air-cargo-backend
cd ts-air-cargo-backend

# Step 2: Initialize Poetry project
poetry init --no-interaction \
  --name "ts-air-cargo-backend" \
  --description "Logistics platform Chine-Afrique backend API" \
  --author "Your Name <your.email@example.com>" \
  --python "^3.13"

# Step 3: Add Django and core dependencies
poetry add django==5.2
poetry add "psycopg[binary]"  # PostgreSQL adapter
poetry add django-environ  # Environment variables
poetry add gunicorn  # WSGI server
poetry add whitenoise  # Static files serving

# Step 4: Add Django Ninja (API framework)
poetry add django-ninja
poetry add django-ninja-extra  # Extra utilities
poetry add pydantic pydantic-settings  # Validation

# Step 5: Add Django Channels (WebSocket)
poetry add channels[daphne]  # Includes Daphne ASGI server
poetry add channels-redis  # Redis channel layer

# Step 6: Add Celery (Background tasks)
poetry add celery[redis]
poetry add django-celery-beat  # Periodic tasks
poetry add django-celery-results  # Task results storage
poetry add flower  # Celery monitoring (dev tool)

# Step 7: Add security & CORS
poetry add djangorestframework-simplejwt  # JWT auth
poetry add django-cors-headers  # CORS for React frontend

# Step 8: Add file storage
poetry add django-storages[s3]  # S3-compatible storage (DO Spaces)
poetry add pillow  # Image processing

# Step 9: Development dependencies
poetry add --group dev pytest pytest-django pytest-cov
poetry add --group dev factory-boy faker  # Test fixtures
poetry add --group dev django-debug-toolbar
poetry add --group dev django-extensions  # shell_plus, etc.
poetry add --group dev black ruff mypy  # Code quality
poetry add --group dev pre-commit  # Git hooks

# Step 10: Create Django project
poetry run django-admin startproject config .

# Step 11: Create Django apps structure
poetry run python manage.py startapp accounts  # User management
poetry run python manage.py startapp colis  # Colis management
poetry run python manage.py startapp vols  # Vols/Manifestes
poetry run python manage.py startapp notifications  # WhatsApp notifications
poetry run python manage.py startapp tracking  # Client tracking

# Step 12: Create settings structure
mkdir config/settings
touch config/settings/__init__.py
touch config/settings/base.py  # Base settings
touch config/settings/local.py  # Local development
touch config/settings/production.py  # Production
```

**Project Structure Created:**

```
ts-air-cargo-backend/
├── pyproject.toml          # Poetry dependencies
├── poetry.lock             # Locked versions
├── manage.py               # Django CLI
├── config/                 # Project config
│   ├── __init__.py
│   ├── settings/
│   │   ├── __init__.py
│   │   ├── base.py        # Base settings
│   │   ├── local.py       # Dev settings
│   │   └── production.py  # Production settings
│   ├── urls.py            # URL routing
│   ├── asgi.py            # ASGI config (Channels)
│   └── wsgi.py            # WSGI config (Gunicorn)
├── accounts/              # Authentication app
├── colis/                 # Colis management
├── vols/                  # Vols/Manifestes
├── notifications/         # Notifications service
├── tracking/              # Client tracking
├── static/                # Static files (collectstatic)
├── media/                 # Uploaded files (local dev)
└── logs/                  # Application logs
```

**Architectural Decisions Provided:**

**Language & Runtime:**
- Python 3.13 (latest stable, performance improvements)
- Django 5.2 (latest, async views, improved ORM)
- Poetry for dependency management (reproducible builds)

**API Framework:**
- **Django Ninja** (added manually, FastAPI-like syntax)
- Pydantic schemas for validation
- OpenAPI/Swagger auto-generated documentation
- Async view support for high-concurrency endpoints

**Database:**
- PostgreSQL 16 with multi-tenant support
- Django ORM + custom managers for tenant isolation
- Migrations handled by Django
- Connection pooling (pgbouncer recommended production)

**Background Jobs:**
- **Celery** for async task processing
- **Redis** as message broker and result backend
- Celery Beat for scheduled tasks (rapports quotidiens)
- Flower for Celery monitoring (dev/staging)

**Real-Time Communication:**
- **Django Channels** for WebSocket support
- **Daphne** ASGI server (production)
- Redis channel layer for horizontal scaling
- Async consumers for dashboard live updates

**Authentication & Security:**
- Django authentication system (PBKDF2 hashing)
- JWT tokens for API (djangorestframework-simplejwt or custom)
- CORS configured for frontend origin
- HTTPS enforced (production settings)
- CSRF protection (cookie-based for same-origin)

**Testing Framework:**
- **Pytest** + pytest-django
- Factory Boy for test fixtures
- Coverage.py for code coverage reports
- Pre-configured test settings

**Code Quality:**
- **Black** formatter (auto-format Python code)
- **Ruff** linter (fast Rust-based, replaces flake8/isort)
- **mypy** for static type checking
- Pre-commit hooks configured

**Development Environment:**
- Docker + Docker Compose (local development)
- Hot-reload with runserver_plus
- Django Debug Toolbar
- django-extensions (shell_plus, etc.)

**Deployment:**
- Production settings separated (production.py)
- Environment variables via django-environ
- Static files: WhiteNoise (served by Nginx on VPS)
- Media files: Local VPS storage or DigitalOcean Spaces
- Gunicorn WSGI server (HTTP endpoints)
- Daphne ASGI server (WebSocket endpoints)
- **Infrastructure:** VPS Hostinger with Nginx reverse proxy

---

### Frontend Stack: Vite + React + Tailwind + shadcn/ui

**Initialization Commands:**

```bash
# Step 1: Create Vite React TypeScript app
npm create vite@latest ts-air-cargo-frontend -- --template react-ts

cd ts-air-cargo-frontend

# Step 2: Install Tailwind CSS v4
npm install -D tailwindcss@next postcss autoprefixer
npx tailwindcss init -p

# Step 3: Initialize shadcn/ui
npx shadcn@latest init
# Prompts:
# - TypeScript: yes
# - Style: Default
# - Base color: Slate (professional logistics)
# - CSS variables: yes

# Step 4: Install core dependencies
npm install @tanstack/react-query axios zustand
npm install react-router-dom  # Multi-interface routing
npm install date-fns  # Date formatting (lighter than moment.js)

# Step 5: PWA Support (offline-first)
npm install -D vite-plugin-pwa workbox-precaching workbox-routing
npm install idb  # IndexedDB wrapper

# Step 6: Development tools
npm install -D @typescript-eslint/eslint-plugin @typescript-eslint/parser
npm install -D prettier eslint-config-prettier
```

**Architectural Decisions Provided:**

**Language & Framework:**
- TypeScript 5.x (strict mode)
- React 19 (latest, improved hooks, concurrent features)
- React Router v6 (routing 7 interfaces)

**Build Tooling:**
- **Vite 6** (ultra-fast HMR, Rollup production builds)
- ESBuild for TypeScript transpilation
- PostCSS for Tailwind processing
- Tree-shaking automatic

**Styling Solution:**
- **Tailwind CSS v4** (CSS-first config, new performance engine)
- **shadcn/ui** components (Radix UI primitives, fully copiable)
- CSS Modules support (scoped styles when needed)
- Dark mode support (class-based strategy)

**State Management:**
- **Zustand** (lightweight, < 1KB, no boilerplate)
- TanStack Query for server state (caching, invalidation)
- React Context for theme/auth global state

**Data Fetching:**
- **TanStack Query** (React Query v5)
- Axios HTTP client (interceptors for JWT tokens)
- Optimistic updates (offline-first UX)
- Automatic retry with exponential backoff

**PWA & Offline:**
- **vite-plugin-pwa** (service worker generation)
- **Workbox** strategies (Cache-First, Network-First)
- **IndexedDB** (idb library) for local data persistence
- Background sync API (sync queue when online)

**Testing (to be added):**
- Vitest (Vite-native test runner)
- Testing Library (React Testing Library)
- Playwright (E2E tests)

**Code Organization:**
```
src/
├── app/              # App-level config (Router, Providers)
├── components/       # shadcn/ui + custom components
│   ├── ui/          # shadcn/ui components
│   └── features/    # Feature-specific components
├── lib/             # Utilities, API clients, helpers
├── stores/          # Zustand stores
├── hooks/           # Custom React hooks
├── pages/           # Route pages (7 interfaces)
└── types/           # TypeScript types/interfaces
```

---

### Decoupled Architecture Diagram

```
┌────────────────────────────────────────────────────────┐
│                  FRONTEND (PWA)                        │
│  Vite + React + Tailwind + shadcn/ui                   │
│  ┌──────────┬──────────┬──────────┬──────────────┐     │
│  │ Agent    │ Agent    │ Agent    │ Admins (3x)  │     │
│  │ Chine    │ Mali     │ RCI      │ Dashboards   │     │
│  └──────────┴──────────┴──────────┴──────────────┘     │
│  │ Client Portal (Mobile-First)                  │     │
│  └───────────────────────────────────────────────┘     │
│                                                         │
│  - Service Worker (offline-first)                      │
│  - IndexedDB (local queue sync)                        │
│  - TanStack Query (server state cache)                 │
│                                                         │
│  Deploy: Vercel / Netlify / Cloudflare Pages           │
└─────────────────┬──────────────────────────────────────┘
                  │
                  │ REST API (Django Ninja)
                  │ WebSocket (Django Channels)
                  │ CORS configured
                  │
┌─────────────────▼──────────────────────────────────────┐
│                  BACKEND (API)                          │
│  Django 5.2 + Django Ninja + Channels                   │
│                                                         │
│  ┌────────────────────┬─────────────────────────┐      │
│  │ API Endpoints      │ WebSocket Consumers     │      │
│  │ (Django Ninja)     │ (Django Channels)       │      │
│  │                    │                         │      │
│  │ - Auth (JWT)       │ - Dashboard live data   │      │
│  │ - Colis CRUD       │ - Notifications push     │      │
│  │ - Vols/Manifestes  │ - Status updates        │      │
│  │ - Tracking         │                         │      │
│  └────────────────────┴─────────────────────────┘      │
│                                                         │
│  ┌──────────────────────────────────────────────┐      │
│  │ Background Workers (Celery)                  │      │
│  │ - PDF generation (manifestes, rapports)      │      │
│  │ - WhatsApp notifications (queue + retry)     │      │
│  │ - Photo compression/optimization             │      │
│  │ - Scheduled reports (Celery Beat)            │      │
│  └──────────────────────────────────────────────┘      │
│                                                         │
│  Deploy: VPS Hostinger (Nginx + Gunicorn + Daphne)  │
└─────────────────┬───────────────┬──────────────────────┘
                  │               │
         ┌────────▼──────┐  ┌────▼─────────┐
         │  PostgreSQL   │  │    Redis     │
         │  (Multi-      │  │  - Cache     │
         │   tenant)     │  │  - Celery    │
         │               │  │  - Channels  │
         └───────────────┘  └──────────────┘
```

**Communication Protocols:**
- **HTTP REST:** Django Ninja API (CRUD operations)
- **WebSocket:** Django Channels (real-time dashboards)
- **Background:** Celery tasks (async heavy operations)

**Note:** Project initialization using these commands should be the **first epic** in implementation phase.

## Core Architectural Decisions

### Decision Priority Analysis

**Critical Decisions (Block Implementation):**
1. Multi-Tenancy Strategy - PostgreSQL Row-Level Security
2. Authentication & Authorization - JWT with HttpOnly Refresh Tokens
3. File Storage - DigitalOcean Spaces (S3-compatible)
4. WhatsApp Integration - Twilio API
5. Real-Time Communication - WebSocket + Polling Hybrid

**Important Decisions (Shape Architecture):**
6. API Error Handling - Standardized JSON responses
7. Database Migrations - Django migrations + manual data migrations
8. Caching Strategy - Redis multi-layer (API cache + Celery broker)
9. Logging & Monitoring - Structured JSON logs + Sentry

**Deferred Decisions (Post-MVP):**
- Advanced analytics dashboards (BI tools)
- Mobile app (React Native future)
- Payment gateway integration (Stripe - conditionally required)

---

### 1. Multi-Tenancy Strategy

**Decision:** PostgreSQL Row-Level Security (RLS) with `country_id` tenant isolation

**Rationale:**
- Single PostgreSQL database with row-level filtering
- Each model has `country` ForeignKey (Chine, Mali, RCI)
- Django middleware automatically filters queries by authenticated user's country
- Simple, scalable, unified migrations

**Implementation Approach:**

```python
# models/base.py
class TenantAwareModel(models.Model):
    country = models.ForeignKey('Country', on_delete=models.PROTECT)
    
    class Meta:
        abstract = True

# middleware/tenant.py
class TenantMiddleware:
    def __call__(self, request):
        if request.user.is_authenticated:
            request.tenant_country = request.user.country
        # Auto-filter all queries by country
```

**Alternatives Considered:**
- ❌ Separate databases per country - Complex deployment, no cross-country queries
- ❌ Separate schemas - PostgreSQL-specific, migration complexity

**Affects:** All models (Colis, Vol, User, etc.), all API endpoints, all reports

---

### 2. Authentication & Authorization

**Decision:** JWT Access Tokens + HttpOnly Refresh Tokens

**Authentication Flow:**

```
1. Login: POST /api/auth/login
   → Returns: 
     - access_token (short-lived 15min, JSON response)
     - refresh_token (long-lived 7 days, HttpOnly cookie)

2. API Requests: Authorization: Bearer <access_token>

3. Token Refresh (automatic): POST /api/auth/refresh
   → Reads refresh_token from HttpOnly cookie
   → Returns new access_token

4. Logout: POST /api/auth/logout
   → Clears HttpOnly cookie
```

**Authorization (RBAC):**
- 7 roles: Agent Chine, Agent Mali, Agent RCI, Admin Chine, Admin Mali, Admin RCI, Client
- Django permissions system + custom decorators
- Country-based permissions (users can only access their country data)

**Libraries:**
- `djangorestframework-simplejwt` for JWT
- `django-cors-headers` for CORS (React frontend origin)

**Security Features:**
- HTTPS only (production)
- CSRF protection for same-origin requests
- Rate limiting on auth endpoints (django-ratelimit)
- Account lockout after 5 failed login attempts

**Affects:** All API endpoints, frontend auth state management

---

### 3. File Storage (Photos & PDFs)

**Decision:** DigitalOcean Spaces (S3-compatible object storage)

**Rationale:**
- S3-compatible API (easy migration to AWS later if needed)
- CDN integrated (fast photo/PDF delivery globally)
- Simpler pricing than AWS S3
- django-storages supports it natively

**Storage Strategy:**

```
Spaces Structure:
/media/
  ├── photos/colis/{country}/{year}/{month}/{colis_id}/
  │   └── {timestamp}_{filename}.jpg
  ├── manifestes/{country}/{year}/{month}/
  │   └── manifest_{vol_id}_{timestamp}.pdf
  └── rapports/{country}/{year}/{month}/
      └── rapport_{type}_{date}.pdf
```

**Configuration:**

```python
# settings/base.py
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
AWS_S3_ENDPOINT_URL = 'https://nyc3.digitaloceanspaces.com'
AWS_STORAGE_BUCKET_NAME = 'ts-air-cargo'
AWS_S3_REGION_NAME = 'nyc3'
AWS_S3_CUSTOM_DOMAIN = 'ts-air-cargo.nyc3.cdn.digitaloceanspaces.com'
```

**Photo Optimization:**
- Upload original via webcam
- Celery task compresses to 800px max width, 80% quality
- Stores both original + compressed

**Alternatives Considered:**
- ❌ AWS S3 - More complex, expensive for small scale
- ❌ Local filesystem - Not scalable multi-server

**Affects:** Colis photo upload, PDF generation (manifestes, rapports)

---

### 4. WhatsApp Integration

**Decision:** Wachap API for WhatsApp Business

**Rationale:**
- WhatsApp Business API integration
- Cost-effective alternative to Twilio
- Python SDK/REST API support
- Webhook support for delivery status
- Local/regional provider advantage

**Notification Flow:**

```python
# Celery task
@shared_task(bind=True, max_retries=3)
def send_whatsapp_notification(self, phone, template, context):
    try:
        # Wachap API integration
        import requests
        
        response = requests.post(
            settings.WACHAP_API_URL,
            headers={
                'Authorization': f'Bearer {settings.WACHAP_API_TOKEN}',
                'Content-Type': 'application/json'
            },
            json={
                'phone': phone,
                'message': render_template(template, context)
            }
        )
        response.raise_for_status()
        return response.json().get('message_id')
    except Exception as exc:
        # Exponential backoff retry
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
```

**Message Templates:**
1. Colis reçu Chine (avec lien tracking)
2. Vol parti Chine
3. Colis arrivé Mali/RCI
4. Colis disponible retrait

**Deep Links:**
```
whatsapp://send?text=Votre colis {ref} est arrivé!
Suivez-le: https://tsaircargo.com/track/{tracking_code}
```

**Alternatives Considered:**
- ❌ Twilio - More expensive, international provider
- ❌ whatsapp-web.js - Unofficial, unreliable, risk ban

**Cost Estimation:**
- Pricing dependent on Wachap plans
- 5000 colis/jour × 4 messages = 20k messages/jour
- Cost advantage over Twilio expected

**Affects:** Notifications app, Celery queue configuration

---

### 5. Real-Time Communication Strategy

**Decision:** Hybrid WebSocket (Dashboards) + Polling (Client Tracking)

**WebSocket (Django Channels) - For Admins:**

```python
# routing.py
websocket_urlpatterns = [
    path('ws/dashboard/', DashboardConsumer.as_asgi()),
]

# consumers.py
class DashboardConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.country = self.scope['user'].country.code
        self.room_group_name = f'dashboard_{self.country}'
        
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()
    
    async def send_dashboard_update(self, event):
        await self.send(text_data=json.dumps(event['data']))
```

**When to Send Updates:**
- Nouveau colis enregistré (count update)
- Vol validé (status change)
- Colis livré (count update)

**Polling (React Query) - For Clients:**

```typescript
// Frontend - Client tracking
const { data } = useQuery({
  queryKey: ['tracking', trackingCode],
  queryFn: () => fetchTracking(trackingCode),
  refetchInterval: 30000, // Poll every 30s
  staleTime: 25000,
});
```

**Rationale Split:**
- **WebSocket Admins:** Real-time critical (< 3s update requirement)
- **Polling Clients:** Updates less critical (30s acceptable)
- **Cost:** WebSocket = persistent connections (Redis cost), Polling = simpler

**Alternatives Considered:**
- ❌ WebSocket everywhere - Expensive Redis, complex client reconnection
- ❌ Polling everywhere - Slow for admin dashboards (UX requirement < 3s)

**Affects:** Frontend dashboard components, Django Channels consumers, Redis channel layer

---

### 6. API Error Handling Standards

**Decision:** Standardized JSON error responses (RFC 7807 Problem Details)

**Error Response Format:**

```json
{
  "type": "https://api.tsaircargo.com/errors/validation-error",
  "title": "Validation Failed",
  "status": 400,
  "detail": "Le poids du colis doit être positif",
  "instance": "/api/colis/create",
  "errors": {
    "poids": ["Doit être supérieur à 0"]
  }
}
```

**HTTP Status Codes:**
- 200 OK - Success
- 201 Created - Resource created
- 400 Bad Request - Validation error
- 401 Unauthorized - Missing/invalid token
- 403 Forbidden - Insufficient permissions
- 404 Not Found - Resource not found
- 409 Conflict - Business logic conflict (ex: colis déjà livré)
- 429 Too Many Requests - Rate limit exceeded
- 500 Internal Server Error - Unexpected error

**Django Ninja Implementation:**

```python
@api.exception_handler(ValidationError)
def validation_exception_handler(request, exc):
    return api.create_response(
        request,
        {"type": "validation-error", "errors": exc.errors()},
        status=400
    )
```

---

### 7. Database Migrations Strategy

**Decision:** Django migrations + manual data migrations when needed

**Migration Workflow:**

```bash
# Create migration
poetry run python manage.py makemigrations

# Review migration file
cat colis/migrations/0001_initial.py

# Apply migration
poetry run python manage.py migrate

# Rollback if needed
poetry run python manage.py migrate colis 0001
```

**Manual Data Migrations:**
For complex data transformations:

```python
# migrations/0005_migrate_legacy_data.py
from django.db import migrations

def migrate_legacy_colis(apps, schema_editor):
    Colis = apps.get_model('colis', 'Colis')
    # Complex data transformation logic
    pass

class Migration(migrations.Migration):
    dependencies = [('colis', '0004_previous')]
    operations = [
        migrations.RunPython(migrate_legacy_colis),
    ]
```

**Production Migration Strategy:**
1. Test migration on staging copy of production DB
2. Backup production DB before migration
3. Run migration during low-traffic window
4. Monitor for errors (Sentry alerts)

---

### 8. Caching Strategy

**Decision:** Redis multi-layer caching

**Cache Layers:**

1. **API Response Cache** (frequently accessed, rarely changed)
   ```python
   from django.core.cache import cache
   
   @cache_page(60 * 5)  # 5 minutes
   def get_country_statistics(request, country_id):
       # Expensive aggregation query
       pass
   ```

2. **Database Query Cache** (ORM level)
   ```python
   # Cache expensive queries
   countries = cache.get_or_set(
       'all_countries',
       lambda: list(Country.objects.all()),
       timeout=3600
   )
   ```

3. **Celery Broker** (task queue)
   - Redis as Celery message broker
   - Separate Redis DB (db=1 for cache, db=0 for Celery)

4. **Session Storage**
   ```python
   SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
   SESSION_CACHE_ALIAS = 'default'
   ```

**Cache Invalidation:**
```python
# Signal-based cache invalidation
@receiver(post_save, sender=Colis)
def invalidate_dashboard_cache(sender, instance, **kwargs):
    cache.delete(f'dashboard_stats_{instance.country_id}')
```

**Redis Configuration:**
- Single Redis instance (development)
- Redis cluster (production high availability)

---

### 9. Logging & Monitoring

**Decision:** Structured JSON logging + Sentry error tracking

**Logging Setup:**

```python
# settings/base.py
LOGGING = {
    'version': 1,
    'formatters': {
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'format': '%(asctime)s %(name)s %(levelname)s %(message)s'
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/django.log',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 5,
            'formatter': 'json',
        }
    },
    'root': {
        'level': 'INFO',
        'handlers': ['console', 'file']
    }
}
```

**Sentry Integration:**

```python
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

sentry_sdk.init(
    dsn=env('SENTRY_DSN'),
    integrations=[DjangoIntegration()],
    environment=env('ENVIRONMENT'),  # development/staging/production
    traces_sample_rate=0.1,  # 10% performance monitoring
)
```

**Metrics to Track:**
- API response times (P50, P95, P99)
- Celery task durations
- WhatsApp delivery rates
- Photo upload success rates
- Database query performance

**Alerts:**
- Error rate > 1% (Sentry)
- API latency > 5s P95 (custom metric)
- Celery queue backlog > 1000 tasks

---

### Decision Impact Analysis

**Implementation Sequence (Priority Order):**

1. **Multi-tenancy** (affects all models) - Week 1
2. **Authentication** (required for all endpoints) - Week 1
3. **File storage** (needed for colis photos) - Week 2
4. **API error handling** (standard across all endpoints) - Week 2
5. **Caching** (performance optimization) - Week 3
6. **Real-time** (dashboard features) - Week 3-4
7. **WhatsApp** (notifications can be batched) - Week 4
8. **Logging/Monitoring** (ongoing, iterative) - Throughout

**Cross-Component Dependencies:**

```
Multi-Tenancy
    ├── Authentication (users belong to country)
    ├── All Models (inherit TenantAwareModel)
    └── API Endpoints (automatic filtering)

Authentication
    ├── CORS Configuration (frontend origin)
    ├── JWT Middleware (all API requests)
    └── Authorization (RBAC permissions)

File Storage
    ├── Celery (async photo compression)
    └── PDF Generation (manifest/rapport storage)

Real-Time
    ├── Redis (channel layer)
    ├── Django Channels (WebSocket consumers)
    └── Frontend (WebSocket client + React Query)

WhatsApp
    ├── Celery (async task queue)
    ├── Redis (broker)
    └── Webhook endpoint (delivery status)
```

**Technology Version Summary:**

| Component | Technology | Version | Production Ready |
|-----------|-----------|---------|------------------|
| Language | Python | 3.13 | ✅ |
| Framework | Django | 5.2 | ✅ |
| API | Django Ninja | Latest | ✅ |
| Database | PostgreSQL | 16 | ✅ |
| Cache/Queue | Redis | 7.x | ✅ |
| Task Queue | Celery | 5.x | ✅ |
| WebSocket | Django Channels | 4.x | ✅ |
| Storage | DO Spaces | S3 API | ✅ |
| WhatsApp | Wachap API | Current | ✅ |
| Frontend | React | 19 | ✅ |
| Build | Vite | 6 | ✅ |
| Styling | Tailwind | 4.0 | ✅ |
| Components | shadcn/ui | 3.8.4 | ✅ |

**Next Steps After Architecture:**
1. Generate `project-context.md` (AI agent guidelines)
2. Create Epics & Stories from PRD + Architecture
3. Initialize projects (Django backend, React frontend)
4. Begin Epic 1: Project Setup & Infrastructure
