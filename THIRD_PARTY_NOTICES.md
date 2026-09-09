# Third-party notices

## vnstock-js

The SSI iBoard WebSocket subscription envelope and pipe-delimited frame mapping in
`backend/app/market_data/providers/ssi_realtime.py` are adapted from
[ttqteo/vnstock-js](https://github.com/ttqteo/vnstock-js), version 1.5.1 / commit
`e5a789c`, licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).

The terminal keeps prices in raw VND and adds stricter frame, symbol, session, generation,
and provenance validation. It does not bundle the JavaScript package; one captured quote
frame is retained in a regression test for the adapted parser.

This software notice does not grant rights to upstream market data. Source-data access and
redistribution remain subject to the terms of the upstream websites and data providers.
