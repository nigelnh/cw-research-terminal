"""Local-only UX fixtures. Never imports app.main, credentials, databases or FiinQuant.
Run: backend/.venv/bin/python tools/ux_preview.py (port 8502).
This is a UI review harness; production API filtering is exercised separately with PostgreSQL tests.
"""
import asyncio
from datetime import date, datetime, timedelta, timezone
import json
import math

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3001", "http://127.0.0.1:3001"], allow_methods=["*"], allow_headers=["*"])
scenario = "last-session"
# Values are deliberately fixed fixtures, not current market quotes.
STAMP = "2026-09-01T07:45:00+00:00"
SPEC = []
for i, (sym, und, issuer, strike, ratio, maturity) in enumerate([
    ("CHPG2602", "HPG", "SSI", 26000, 2, "2026-09-25"),
    ("CVPB2615", "VPB", "ACBS", 28500, 2, "2027-02-17"),
    ("CTCB2601", "TCB", "ACBS", 37000, 4, "2026-10-26"),
] + [(f"CFPT26{i:02d}", "FPT", ["SSI","KIS","HSC","ACBS"][i%4], 85000+i*500, 5, "2027-03-12") for i in range(1,31)]):
    SPEC.append(dict(symbol=sym, instrument_type="CW", underlying_symbol=und, issuer=issuer,
                     strike_price=strike, exercise_ratio=ratio, maturity_date=maturity,
                     last_trading_date=(date.fromisoformat(maturity)-timedelta(days=2)).isoformat(),
                     metadata_verification="CONFLICTING" if sym=="CTCB2601" else "VERIFIED_CURRENT", data_quality="COMPLETE", status="ACTIVE"))


def quote(sym):
    kind = "CW" if sym.startswith("C") else "INDEX" if sym=="VNINDEX" else "STOCK"
    last = {"HPG":29.5,"VPB":28.1,"TCB":36.2,"FPT":96.5,"VNINDEX":1682.47,"CHPG2602":1.84,"CVPB2615":1.21}.get(sym, 1.52)
    change = .1 if kind=="CW" else -2.37 if kind=="INDEX" else -.35
    ref = last-change
    return dict(Symbol=sym, InstrumentType=kind, Traded=last, Ref=ref, Change=change, ChangePercent=change/ref,
                Bid1_Prc=last-.01, Ask1_Prc=last+.01, Total_Vol=1542000 if kind=="STOCK" else 123400,
                ExchangeTime=int(datetime.fromisoformat(STAMP).timestamp()*1000), Under_Symbol=next((s["underlying_symbol"] for s in SPEC if s["symbol"]==sym), None))


def analytics(sym):
    return dict(isAvailable=sym!="CTCB2601", unavailableReason="METADATA_CONFLICT" if sym=="CTCB2601" else None,
                ivBid=.31,ivTrade=.325,ivAsk=.34,historicalVolatility=.287,theoreticalPrice=1750,
                delta=.28,gamma=.000045,theta=-4.25,vega=11.82,rho=2.31,moneynessRatio=1.1346,
                moneynessCategory="ITM",contractState="ACTIVE",dte=24,greeksVolatilitySource="IV_MID")


@app.get('/__scenario')
def get_scenario(): return {"scenario":scenario}
@app.post('/__scenario/{state}')
def set_scenario(state: str):
    global scenario
    if state in ["live", "last-session", "empty", "error"]: scenario=state
    return {"scenario":scenario}

@app.get('/api/instruments')
def instruments():
    if scenario=="error": return JSONResponse({"detail":"Fixture service unavailable"}, status_code=503)
    return {"items": [] if scenario=="empty" else SPEC, "total":len(SPEC), "active_count":len(SPEC)}
@app.get('/api/instruments/default-universe')
def defaults(): return {"items":[],"known_through":"2026-09-01"}
@app.get('/api/market/dashboard')
def dashboard(symbols: str=""):
    if scenario=="error": return JSONResponse({"detail":"Fixture market unavailable"},status_code=503)
    rows=[]
    for sym in symbols.split(','):
        if not sym: continue
        row=quote(sym)
        state="LIVE" if scenario=="live" else "UNAVAILABLE" if scenario=="empty" else "LAST_SESSION"
        if scenario=="empty": row={"Symbol":sym,"InstrumentType":row["InstrumentType"]}
        if scenario!="live": row.update(Bid1_Prc=None,Ask1_Prc=None)
        rows.append({**row,"displayState":state,"analytics":analytics(sym) if scenario!="empty" and sym.startswith('C') else None,
                     "provenance":{"quote":{"state":state,"source":"UX_FIXTURE","asOf":STAMP if scenario!="empty" else None,"sessionDate":"2026-09-01"},
                                   "book":{"state":"UNAVAILABLE","source":"NONE"},"analytics":{"state":state,"source":"UX_FIXTURE","asOf":STAMP}}})
    return dict(rows=rows,as_of=STAMP,market_session="CONTINUOUS_AM" if scenario=="live" else "CLOSED_POST_MARKET",market_session_active=scenario=="live",latest_completed_session="2026-09-01",calendar_confidence="CONFIRMED")
@app.get('/api/market/history/{symbol}')
def history(symbol: str):
    if scenario=="error":return JSONResponse({"detail":"History unavailable"},status_code=503)
    if scenario=="empty":return []
    base=quote(symbol)["Traded"]*(1 if symbol=="VNINDEX" else 1000)
    result=[]
    for i in range(260):
        day=date(2026,9,1)-timedelta(days=259-i)
        if day.weekday()>4:continue
        value=base*(.80+.20*i/260+.035*math.sin(i/8))
        result.append(dict(symbol=symbol,date=day.isoformat(),open=round(value*.996,2),close=round(value,2),high=round(value*1.014,2),low=round(value*.985,2),volume=150000+i*1100,ref_price=round(value*.993,2)))
    return result

NEWS=[dict(id=f"news_{i}",symbol=["HPG","VPB","FPT","TCB"][i%4],
           title="Thông báo ngày đăng ký cuối cùng thực hiện quyền nhận cổ tức bằng tiền và tài liệu họp đại hội đồng cổ đông năm 2026",
           title_en=("Notice of record date for cash dividend and supporting materials for the 2026 annual general meeting" if i%3==0 else "Board resolution on the cash dividend distribution plan"),
           title_en_exact=i%3!=0,category_en="Dividend disclosure",content_type="exchange_disclosure",source="HOSE",source_language="vi",source_url="https://www.hsx.vn",
           published_at=(date(2026,9,1)-timedelta(days=i//3)).isoformat(),display_date=(date(2026,9,1)-timedelta(days=i//3)).isoformat(),date_kind="published",summary="Công ty công bố tài liệu và thời gian thực hiện quyền cổ đông theo thông báo chính thức.") for i in range(88)]
NEWS.insert(0,{**NEWS[0],"id":"event_1","title_en":"Cash dividend · upcoming ex-date","content_type":"company_event","source":"SSI","date_kind":"ex_date","display_date":"2026-09-10","published_at":"2026-09-10"})
@app.get('/api/research/feed/facets')
def facets():return {"symbols":["FPT","HPG","TCB","VPB","VNM"]}
@app.get('/api/research/feed')
def feed(symbols:str|None=None,q:str="",content_type:str|None=None,date_from:str="",date_to:str="",cursor:str="0",limit:int=40):
    if scenario=="error":return JSONResponse({"detail":"Feed unavailable"},status_code=503)
    rows=[] if scenario=="empty" else [x for x in NEWS if (symbols is None or x['symbol'] in symbols.split(',')) and (not q or q.lower() in (x['title_en']+' '+x['title']+' '+x['symbol']).lower()) and (not content_type or x['content_type']==content_type) and (not date_from or x['display_date']>=date_from) and (not date_to or x['display_date']<=date_to)]
    start=int(cursor);more=start+limit<len(rows)
    return dict(items=rows[start:start+limit],count=len(rows[start:start+limit]),has_more=more,next_cursor=str(start+limit) if more else None,next_before=None)
@app.get('/api/research/corporate-actions/{symbol}')
def events(symbol:str):return dict(symbol=symbol,items=[],count=0)
@app.get('/api/research/corporate-actions')
def event_query(symbol:str="HPG"):return dict(symbol=symbol,items=[dict(id=1,action_type="CASH_DIVIDEND",event_label="Cash dividend",ex_date="2026-09-10",record_date="2026-09-11",payment_date="2026-09-25",cash_amount_vnd=500,source="SSI")],count=1)
@app.post('/api/ai/chat')
async def chat():
    async def stream():
        for token in ["### Fixture response\n\n", "This is a local UI test, ", "using **fixed sample values**.\n\n", "- Quote and analytics timestamps are shown separately.\n", "- Contract dates remain visible in Overview.\n", "\nStop keeps this partial response. Retry reuses the original question and context."]:
            yield 'data: '+json.dumps({"content":token})+'\n\n'
            await asyncio.sleep(.7)
        yield 'data: [DONE]\n\n'
    return StreamingResponse(stream(),media_type='text/event-stream')
@app.websocket('/ws/market')
async def websocket(ws:WebSocket):
    await ws.accept()
    await ws.send_json(dict(type="status",market_session="CONTINUOUS_AM" if scenario=="live" else "CLOSED_POST_MARKET",market_session_active=scenario=="live",connected=True))
    if scenario=="live":
        await ws.send_json(dict(type="snapshots",rows=[quote(s) for s in ["HPG","VPB","VNINDEX"]+[x['symbol'] for x in SPEC]]))
        for spec in SPEC:
            await ws.send_json(dict(type="analytics_patch",symbol=spec['symbol'],analytics={"calculated_at":STAMP,"is_available":spec['symbol']!="CTCB2601","iv_bid":.31,"iv_trade":.325,"iv_ask":.34,"historical_volatility":.287,"moneyness":1.1346,"moneyness_category":"ITM","model_inputs":{"days_to_expiry":24},"greeks":{"delta":.28,"gamma":.000045,"theta":-4.25,"vega":11.82,"theoretical_price":1750,"volatility_source":"IV_MID"}}))
    try:
        while True: await ws.receive_text()
    except Exception: pass

if __name__=='__main__': uvicorn.run(app,host='127.0.0.1',port=8502)
