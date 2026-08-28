export * from "./mock_market_data_provider";
export * from "./mock_instrument_provider";
export * from "./mock_historical_data_provider";
// NOTE: there is deliberately NO mock quant provider. The frontend owns no financial
// math - Black-Scholes / Greeks / IV / HV are computed exclusively by the Python
// backend (app.quant.*) and verified in backend/tests/test_quant_*.py. Any TS
// reimplementation would be an untested copy that silently drifts from production.
