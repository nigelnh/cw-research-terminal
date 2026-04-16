# HQ Stock Trading Dashboard

Real-time trading dashboard with React frontend and Node.js backend.

## Architecture

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│  SSI iBoard     │ ───> │  Node.js Server │ ───> │  React Frontend │
│  WebSocket      │      │  (port 8787)    │      │  (port 3000)    │
└─────────────────┘      └─────────────────┘      └─────────────────┘
```

- **Server**: Connects to SSI iBoard WebSocket, parses S# messages, broadcasts normalized updates
- **Frontend**: React + TypeScript with OOP table framework, receives patches and only updates changed cells

## Quick Start

### Prerequisites
- Node.js 18+

### 1. Start the backend server

```bash
cd server
npm install
npm run dev
```

Server will connect to upstream market socket and listen on port 8788.

### 2. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 in your browser.

## Project Structure

```
├── frontend/
│   └── src/
│       ├── app/           # Layout components (Topbar, panels)
│       ├── design/        # Design tokens, colors, global CSS
│       ├── tables/
│       │   ├── core/      # OOP table framework (TableBase, ColumnBase, TableView)
│       │   └── equity/    # Equity table implementation
│       └── data/          # WebSocket client, React hooks
│
├── server/
    └── src/
        ├── ssi/           # SSI WebSocket client, message parser
        ├── ws/            # Client hub for broadcasting
        └── index.ts       # Entry point
```

## Table Framework (OOP + Inheritance)

The table system uses object-oriented design with fixed pixel sizing:

- `TableBase<T>` - Abstract base class defining row height, header height, columns
- `ColumnBase<T>` - Base column with fixed width (px), alignment, formatting
- `PriceColumn<T>` - Extends ColumnBase, formats to 2 decimal places
- `QuantityColumn<T>` - Extends ColumnBase, formats with thousand separators
- `TableView<T>` - React component that renders any TableBase with change detection + flash effect

## API Message Schema

Server → Client WebSocket messages:

```typescript
// Full row snapshot (sent on connect or new symbol)
{ type: "snapshot", symbol: "HPG", row: EquityRow, ts: number }

// Partial update (only changed fields)
{ type: "patch", symbol: "HPG", patch: Partial<EquityRow>, ts: number }

// Connection status
{ type: "status", connected: boolean, message: string }
```
