import asyncio
import json
import httpx
import websockets

async def main():
    print("=" * 70)
    print("  E2E LIVE MARKET SMOKE TEST: FastAPI + FiinQuant -> /ws/market")
    print("=" * 70)

    # 1. Test Root Health
    async with httpx.AsyncClient() as client:
        r_root = await client.get("http://127.0.0.1:8501/health")
        print(f"[REST] /health -> {r_root.status_code}: {r_root.json()}")

        r_market = await client.get("http://127.0.0.1:8501/api/market/health")
        print(f"[REST] /api/market/health -> {r_market.status_code}: {r_market.json()}")

    # 2. Test WebSocket Gateway
    uri = "ws://127.0.0.1:8501/ws/market"
    print(f"\n[WS] Connecting to {uri}...")

    async with websockets.connect(uri) as ws:
        init_frame = await ws.recv()
        print(f"[WS] Received Initial Frame: {init_frame}")

        # Subscribe to active symbols
        sub_msg = {"type": "subscribe", "symbols": ["HPG", "CHPG2602", "VNINDEX"]}
        print(f"[WS] Sending Subscription: {sub_msg}")
        await ws.send(json.dumps(sub_msg))

        print("[WS] Listening for live market patches for 12 seconds...")
        events_received = []
        try:
            while True:
                msg_raw = await asyncio.wait_for(ws.recv(), timeout=12.0)
                msg = json.loads(msg_raw)
                events_received.append(msg)
                print(f"  • [WS Event ({msg.get('type')})] Symbol: {msg.get('symbol') or msg.get('rows')} - Payload: {msg.get('patch') or ''}")
                if len(events_received) >= 5:
                    break
        except asyncio.TimeoutError:
            print(f"[WS] Collection window completed. Total events: {len(events_received)}")

        # Unsubscribe
        unsub_msg = {"type": "unsubscribe", "symbols": ["CHPG2602"]}
        await ws.send(json.dumps(unsub_msg))
        print("[WS] Sent unsubscribe. Closing cleanly.")

    print("\n" + "=" * 70)
    print(f"  E2E LIVE SMOKE TEST FINISHED ({len(events_received)} live frames received)")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
