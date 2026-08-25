# FiinQuant Python SDK Reconnaissance & POC Harness
**Directory:** `backend/poc/fiinquant/`  
**Classification:** `POC / RECONNAISSANCE ONLY` (Not Production Code)

---

## 1. Security & Antivirus Status Notice

> **Security Note (`AV_DETECTION_UNRESOLVED`):**  
> Local Avast File Shield heuristically detected a compiled FiinQuantX Python artifact as `Python:Agent-XO [Cryp]`. This may be related to vendor package obfuscation/packing (`VENDOR_PACKAGE_OBFUSCATION_OR_PACKING_OBSERVED`), but the classification is unresolved. The project does not disable antivirus, patch vendor packages, or broadly whitelist the repository. FiinQuant runtime integration remains conditional on clean reproducibility and security validation.

### Package Provenance & Cryptographic Hashes
* **Python Runtime:** Python 3.13.2 (macOS arm64)
* **Official Package:** `FiinQuantX v0.1.67`
* **Package Source:** `https://fiinquant.github.io/fiinquantx/simple`
* **Wheel URL:** `https://github.com/fiinquant/fiinquantx/releases/download/0.1.67/fiinquantx-0.1.67-py3-none-any.whl`
* **Wheel SHA-256:** `92d8f1dc44717e2d895176668a811c8f3940a4cd74de2da8738572ed626276eb`
* **SignalR Dependency:** `signalrcore==0.9.71` + `msgpack==1.0.2` (`COMPATIBILITY_WORKAROUND_REQUIRED`: Pinned to bypass a breaking negotiation parser defect in unpinned `signalrcore 1.0.2` against the FiinQuant SignalR server).

---

## 2. Setup & Execution (Isolated Environment Only)

### A. Dedicated Virtual Environment Installation
```bash
cd backend/poc/fiinquant
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

### B. Credentials Setup
Copy `.env.example` to `.env` and configure your credentials:
```bash
cp .env.example .env
```
Fill in:
```ini
FIINQUANT_USERNAME=your_username
FIINQUANT_PASSWORD=your_password
FIINQUANT_TEST_CW_SYMBOL=YOUR_ACTIVE_HOSE_CW_SYMBOL
```

### C. Run Real-Time Probe
```bash
.venv/bin/python fiinquant_realtime_probe.py
```

### D. Run Historical & Metadata Probe
```bash
.venv/bin/python fiinquant_history_probe.py
```

### E. Run Unit Tests (Normalization Helpers)
```bash
.venv/bin/pytest test_normalization_helpers.py
```

---

## 3. Key Findings from Reconnaissance

1. **SignalR Transport:** `FiinQuantX` communicates over SignalR with hub URL `https://fiinquant-realtime.fiintrade.vn/RealtimeHub` (JSON protocol v1).
2. **Dual-Connection Architecture:** `Trading_Data_Stream` and `BidAsk` instantiate separate `HubConnectionBuilder` WebSocket connections.
3. **Symbol Subscription Lifecycle:** Neither class supports dynamic runtime `subscribe()` / `unsubscribe()`. Modifying symbols requires stopping and recreating the stream thread (`RESTART_REQUIRED`).
4. **Historical Price Semantics:** `Fetch_Trading_Data` defaults to `adjusted=True` for corporate actions (decimal-valued dividend adjusted bars). Realtime stream prices represent raw exchange matching prices.
5. **MasterData Restrictions:** Free tier accounts lack entitlement (`403 Forbidden`) to `BasicInfor` master endpoints; CW static specifications (strike, ratio, expiry) are loaded from local curated fixtures.
