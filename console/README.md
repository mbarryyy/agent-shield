# Elydora Console

Web dashboard for the Elydora Responsibility Protocol. Provides agent management, operation inspection, epoch visualization, audit log querying, and compliance export tools.

## Tech Stack

- **Framework:** Next.js 16.1 (App Router)
- **Language:** TypeScript 5.7
- **UI:** React 19, Tailwind CSS 4
- **Data Fetching:** SWR 2.3
- **Deployment:** Cloudflare Pages (static export)

## Project Structure

```
src/
├── app/
│   ├── layout.tsx                    # Root layout with AppShell
│   ├── page.tsx                      # Dashboard — stats, recent operations, quick actions
│   ├── globals.css                   # Theme variables, global styles
│   ├── agents/
│   │   ├── page.tsx                  # Agent list, search, registration
│   │   └── [agent_id]/page.tsx       # Agent details, keys, freeze/unfreeze
│   ├── operations/
│   │   ├── page.tsx                  # Operations log with filtering
│   │   └── [operation_id]/page.tsx   # Operation details and verification
│   ├── epochs/
│   │   ├── page.tsx                  # Epoch list with root hashes
│   │   └── [epoch_id]/page.tsx       # Epoch details, Merkle proof visualization
│   ├── exports/
│   │   └── page.tsx                  # Create and download compliance exports
│   ├── audit/
│   │   └── page.tsx                  # Audit log query builder
│   ├── login/page.tsx                # Login form
│   ├── register/page.tsx             # Registration form
│   └── jwks/page.tsx                 # Public key display
├── components/
│   ├── AppShell.tsx                  # Main layout wrapper with sidebar
│   ├── AgentDetailClient.tsx         # Agent info and key management
│   ├── AgentRegistrationForm.tsx     # Register new agent form
│   ├── OperationDetailClient.tsx     # Operation inspection and verification
│   ├── OperationDetailCard.tsx       # Operation data display
│   ├── EpochDetailClient.tsx         # Epoch proof and verification
│   ├── ChainVisualization.tsx        # Merkle chain visualization
│   ├── VerificationChecklist.tsx     # Proof verification UI
│   └── ui/
│       ├── PageHeader.tsx            # Page title and breadcrumbs
│       ├── DataTable.tsx             # Sortable, paginated table
│       ├── Modal.tsx                 # Dialog component
│       ├── SearchInput.tsx           # Search/filter input
│       ├── StatusBadge.tsx           # Status indicator
│       ├── CopyButton.tsx            # Copy-to-clipboard
│       └── Sidebar.tsx               # Navigation sidebar
├── lib/
│   ├── api.ts                        # Typed REST client for all endpoints
│   ├── auth.tsx                      # Auth context and hooks
│   └── hooks.ts                      # SWR data-fetching hooks
└── shared/                           # Shared types (@elydora/shared)
```

## Getting Started

### Prerequisites

- Node.js 18+

### Installation

```bash
npm install
```

### Environment

| Variable | Purpose | Default |
|----------|---------|---------|
| `NEXT_PUBLIC_API_BASE_URL` | Backend API URL | `http://localhost:8787` |

### Development

```bash
npm run dev
```

Runs at `http://localhost:3000` with Turbopack.

### Build

```bash
npm run build
```

Produces a static export in `out/`. A post-build script removes stale `_redirects` files.

### Deployment

```bash
npm run deploy
```

Deploys the `out/` directory to Cloudflare Pages.

### Type Checking

```bash
npm run typecheck
```

## Pages

| Path | Description |
|------|-------------|
| `/` | Dashboard with stats, recent operations, and quick actions |
| `/agents` | List, search, and register agents |
| `/agents/[agent_id]` | Agent details, key management, freeze/unfreeze |
| `/operations` | Browse operations with agent and type filters |
| `/operations/[operation_id]` | Operation details, chain hash verification |
| `/epochs` | List epochs with root hashes and leaf counts |
| `/epochs/[epoch_id]` | Epoch details with Merkle proof visualization |
| `/exports` | Create and download compliance exports (JSON/PDF) |
| `/audit` | Query builder for audit log with time range and agent filters |
| `/login` | Login |
| `/register` | Register account and organization |
| `/jwks` | Display server public keys in JWK format |
