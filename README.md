# Binance_futures_bot
“A Python-based Binance Futures trading bot that fetches real-time prices, checks balances, and interacts with Binance API securely using environment variables.”
# Binance Futures Trading Bot

A Python-based trading bot for Binance USDT-M Futures.  
It allows you to fetch account details, balances, and prices securely using the Binance Futures API.  
Environment variables are managed with '.env' for safe key storage.

## Features
- Fetch account details from Binance Futures Testnet  
- Secure API authentication with HMAC SHA256 signatures  
- Environment variable support ('.env') for API keys  
- Example implementation for extending into a full trading bot  

## Requirements
- Python 3.8+  
- 'requests'  
- 'python-dotenv'

## Install dependencies:
bash
pip install -r requirements.txt
                                                                                                                                                                                                                                                                                                                                                                                                                                        ## How to run & test (examples)

Install:
pip install binance-futures-connector requests

Export credentials (In Windows PowerShell):

setx BINANCE_API_KEY "your_testnet_api_key"
setx BINANCE_API_SECRET "your_testnet_api_secret"

Run examples:

1) Get price:

python <file_name.py> price --symbol BTCUSDT


2) Get balance:

python <file_name.py> balance
