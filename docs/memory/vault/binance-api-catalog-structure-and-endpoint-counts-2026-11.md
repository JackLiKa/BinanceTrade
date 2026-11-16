---
title: Binance API catalog structure and endpoint counts (2026-11)
tags:
  - binance
  - api
  - catalog
  - reference
created: '2026-11-16T11:34:13+08:00'
---

# Binance API catalog structure and endpoint counts (2026-11)

Binance Developer Center (developers.binance.com/en) organizes APIs by product catalog. As of 2026-11, the new docs expose 46 OpenAPI schemas totaling 984 paths / 1,079 operations across: Core Trading (Spot REST 44 + WS API 55 + WS Streams 15; Margin 55; USDⓈ-M Futures 83 + 18 + 20; COIN-M Futures 56 + 10 + 19; Options 35 + 10; Wallet 49; Convert 9), Advanced Trading (Portfolio Margin 85; PM Pro 20; Algo 12; Alpha 6 + 13 streams; Copy 2; Institutional Loan 15; Stocks 16 + 7), Investment & Services (Simple Earn 41; Staking 37; Crypto Loan 12; VIP Loan 14; Dual Investment 4; Discount Buy 4; Mining 13; Fiat 5; Gift Card 6; Pay/C2C/Rebate 1 each), VIP & Institutional (Sub Account 45; CaaS 26; OMS 18; KYC SaaS 12; Fund Account 9; Link Plus 8; Spot Block Matching 7; VIP CaaS 6; VIP Service 9), and Web3 Prediction Trading (36 + 15 streams). Protocols: REST, WebSocket API, WebSocket Streams, plus legacy Spot FIX and SBE. Base paths: /api/v3 + /sapi, /fapi, /dapi, /eapi, /papi; auth via X-MBX-APIKEY + HMAC/RSA/Ed25519 signature; user data streams via listenKey. Legacy docs also list NFT and Auto Invest not in the new catalog. Sources: https://developers.binance.com/en/, https://developers.binance.com/en/docs/catalog, https://developers.binance.com/legacy-docs/binance-spot-api-docs/README
