"""
ALPACA AUTOMATED TRADING BOT
=============================

Fully automated trading that:
✓ Scans for signals
✓ Automatically enters positions via Alpaca API
✓ Automatically manages positions (closes at target/stop)
✓ Sends email alerts
✓ Runs on GitHub Actions (your MacBook OFF)

For paper trading on Alpaca.
"""

import os
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# CONFIGURATION (From GitHub Secrets - Don't edit manually)
# ============================================================================

ALPACA_API_KEY = os.environ.get('ALPACA_API_KEY')
ALPACA_SECRET_KEY = os.environ.get('ALPACA_SECRET_KEY')
GMAIL_SENDER = os.environ.get('GMAIL_SENDER')
GMAIL_PASSWORD = os.environ.get('GMAIL_PASSWORD')

TICKERS = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA']
RISK_PER_TRADE = 0.01  # 1% risk per position

# ============================================================================
# ALPACA CLIENT WRAPPER
# ============================================================================

class AlpacaClient:
    """Wrapper for Alpaca trading API"""
    
    def __init__(self, api_key, secret_key, paper=True):
        self.client = TradingClient(api_key, secret_key, paper=paper)
    
    def get_account(self):
        """Get account info (equity, buying power, etc.)"""
        return self.client.get_account()
    
    def get_positions(self):
        """Get all open positions"""
        try:
            return self.client.get_all_positions()
        except:
            return []
    
    def get_orders(self):
        """Get all open orders"""
        try:
            return self.client.get_orders(status='open')
        except:
            return []
    
    def submit_market_order(self, symbol, qty, side):
        """Submit market order (buy/sell immediately)"""
        request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            time_in_force=TimeInForce.DAY
        )
        return self.client.submit_order(request)
    
    def submit_stop_order(self, symbol, qty, stop_price):
        """Submit stop loss order (sells if price drops to stop_price)"""
        request = StopOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            stop_price=stop_price,
            time_in_force=TimeInForce.GTC  # Good Till Cancelled
        )
        return self.client.submit_order(request)
    
    def submit_limit_order(self, symbol, qty, limit_price):
        """Submit limit sell order (sells if price reaches limit_price)"""
        request = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            limit_price=limit_price,
            time_in_force=TimeInForce.GTC
        )
        return self.client.submit_order(request)
    
    def cancel_all_orders(self, symbol=None):
        """Cancel all orders for a symbol (or all if symbol is None)"""
        try:
            orders = self.client.get_orders(status='open')
            for order in orders:
                if symbol is None or order.symbol == symbol:
                    self.client.cancel_order(order.id)
        except:
            pass


# ============================================================================
# TRADING SIGNALS
# ============================================================================

class SignalScanner:
    """Scan for trading signals"""
    
    def __init__(self):
        self.signals = []
    
    def load_data(self, tickers):
        """Download market data for all tickers"""
        print(f"[{self._time()}] Loading market data...")
        data = {}
        
        for ticker in tickers:
            try:
                df = yf.download(ticker, period='1y', progress=False)
                
                # Fix MultiIndex columns
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                
                df.columns = [col.lower() for col in df.columns]
                
                # Use adjusted close
                if 'adj close' in df.columns:
                    df['close'] = df['adj close']
                
                # Keep last 30 days
                data[ticker] = df.tail(30)
                print(f"  ✓ {ticker}")
                
            except Exception as e:
                print(f"  ✗ {ticker}: {e}")
        
        return data
    
    def scan_for_signals(self, data):
        """Check all tickers for trading signals"""
        print(f"\n[{self._time()}] Scanning for signals...")
        
        for ticker, df in data.items():
            
            if len(df) < 25:
                continue
            
            # === REQUIRED: Must be in uptrend ===
            sma_20 = df['close'].rolling(20).mean()
            in_uptrend = df['close'].iloc[-1] > sma_20.iloc[-1]
            
            if not in_uptrend:
                continue
            
            current_price = df['close'].iloc[-1]
            
            # === SIGNAL 1: Mean Reversion Down ===
            # Stock down 2%+ in one day
            yesterday_close = df['close'].iloc[-2]
            ret_today = (current_price - yesterday_close) / yesterday_close
            
            if ret_today < -0.02:
                self.signals.append({
                    'ticker': ticker,
                    'type': 'Mean Reversion Down',
                    'price': current_price,
                    'stop': current_price * 0.99,
                    'target': current_price * 1.02,
                    'description': f"Stock down {abs(ret_today)*100:.1f}% today",
                })
                print(f"  ✓ {ticker}: Mean Reversion Down ({abs(ret_today)*100:.1f}% down)")
            
            # === SIGNAL 2: Breakout 52-Week High ===
            # Price > 52-week high on volume
            high_52w = df['high'].rolling(252).max()
            is_breakout = current_price > high_52w.iloc[-2] * 1.001
            
            vol_today = df['volume'].iloc[-1]
            vol_avg = df['volume'].rolling(20).mean().iloc[-1]
            high_volume = vol_today > vol_avg * 1.5
            
            if is_breakout and high_volume:
                self.signals.append({
                    'ticker': ticker,
                    'type': '52-Week Breakout',
                    'price': current_price,
                    'stop': current_price * 0.99,
                    'target': current_price * 1.02,
                    'description': f"New high, volume {vol_today/vol_avg:.1f}x average",
                })
                print(f"  ✓ {ticker}: 52-Week Breakout (vol {vol_today/vol_avg:.1f}x)")
            
            # === SIGNAL 3: Pullback to SMA ===
            # Price near 20-day SMA with wide range
            sma_20_val = sma_20.iloc[-1]
            pct_from_sma = (current_price - sma_20_val) / sma_20_val
            near_sma = (-0.01 < pct_from_sma < 0.01)
            
            # Wide range = top 25th percentile
            bar_ranges = ((df['high'] - df['low']) / df['close']) * 100
            bar_range_threshold = bar_ranges.quantile(0.75)
            current_bar_range = ((df['high'].iloc[-1] - df['low'].iloc[-1]) / df['close'].iloc[-1]) * 100
            wide_range = current_bar_range > bar_range_threshold
            
            if near_sma and wide_range:
                self.signals.append({
                    'ticker': ticker,
                    'type': 'Pullback to SMA',
                    'price': current_price,
                    'stop': current_price * 0.99,
                    'target': current_price * 1.02,
                    'description': f"At 20-day SMA, wide range {current_bar_range:.2f}%",
                })
                print(f"  ✓ {ticker}: Pullback to SMA (range {current_bar_range:.2f}%)")
    
    @staticmethod
    def _time():
        """Get current time HH:MM format"""
        return datetime.now().strftime('%H:%M')


# ============================================================================
# TRADE EXECUTION
# ============================================================================

class AutoTrader:
    """Automatically execute trades"""
    
    def __init__(self, alpaca_client):
        self.alpaca = alpaca_client
        self.executed_trades = []
    
    def execute_signals(self, signals):
        """Automatically enter all signals"""
        if not signals:
            print(f"\n[{self._time()}] No signals to execute")
            return []
        
        print(f"\n[{self._time()}] Executing {len(signals)} trade(s)...")
        
        account = self.alpaca.get_account()
        account_equity = float(account.equity)
        
        for signal in signals:
            try:
                ticker = signal['ticker']
                entry_price = signal['price']
                stop_price = signal['stop']
                target_price = signal['target']
                
                # Calculate position size (1% risk)
                risk_dollars = account_equity * RISK_PER_TRADE
                risk_per_share = entry_price - stop_price
                shares = int(risk_dollars / risk_per_share)
                
                if shares <= 0:
                    print(f"  ✗ {ticker}: Position too small")
                    continue
                
                # Cap at 15% of account
                max_position_value = account_equity * 0.15
                if shares * entry_price > max_position_value:
                    shares = int(max_position_value / entry_price)
                
                # Submit buy order
                buy_order = self.alpaca.submit_market_order(
                    ticker, shares, OrderSide.BUY
                )
                print(f"  ✓ {ticker}: BUY {shares} @ {entry_price:.2f}")
                
                # Submit stop loss order
                self.alpaca.submit_stop_order(ticker, shares, stop_price)
                print(f"    ├─ Stop: ${stop_price:.2f}")
                
                # Submit profit target order
                self.alpaca.submit_limit_order(ticker, shares, target_price)
                print(f"    └─ Target: ${target_price:.2f}")
                
                self.executed_trades.append({
                    'ticker': ticker,
                    'type': signal['type'],
                    'entry': entry_price,
                    'shares': shares,
                    'stop': stop_price,
                    'target': target_price,
                    'time': self._time(),
                })
                
            except Exception as e:
                print(f"  ✗ {signal['ticker']}: Error - {str(e)[:50]}")
        
        return self.executed_trades
    
    @staticmethod
    def _time():
        return datetime.now().strftime('%H:%M')


# ============================================================================
# EMAIL ALERTS
# ============================================================================

class Alerter:
    """Send email alerts"""
    
    @staticmethod
    def send_execution_alert(executed_trades, account_info=None):
        """Send alert about executed trades"""
        if not executed_trades:
            return
        
        print(f"\n[{Alerter._time()}] Sending email alert...")
        
        subject = f"[AUTO TRADE] {len(executed_trades)} Position(s) - {datetime.now().strftime('%Y-%m-%d')}"
        
        body = f"""
AUTOMATED TRADING BOT - EXECUTION REPORT
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}

{len(executed_trades)} position(s) automatically entered:

"""
        
        for i, trade in enumerate(executed_trades, 1):
            body += f"""
Trade #{i}: {trade['ticker']}
├─ Signal: {trade['type']}
├─ Entry: ${trade['entry']:.2f}
├─ Shares: {trade['shares']}
├─ Stop Loss: ${trade['stop']:.2f}
└─ Profit Target: ${trade['target']:.2f}

"""
        
        body += """
STATUS:
✓ Positions are LIVE (entered at market)
✓ Stop loss orders are ACTIVE
✓ Profit target orders are ACTIVE
✓ No further action needed

MANAGEMENT:
- System will close at profit target OR stop loss (whichever hits first)
- If neither hits in 3 days, position will be closed manually
- Check Alpaca dashboard to verify

Check your Alpaca account: https://app.alpaca.markets/

---
Paper Trading Bot
Auto-generated - Do not reply
"""
        
        try:
            server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
            server.login(GMAIL_SENDER, GMAIL_PASSWORD)
            
            msg = MIMEMultipart()
            msg['From'] = GMAIL_SENDER
            msg['To'] = GMAIL_SENDER
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))
            
            server.send_message(msg)
            server.quit()
            
            print(f"  ✓ Alert sent to {GMAIL_SENDER}")
            
        except Exception as e:
            print(f"  ✗ Failed to send email: {e}")
    
    @staticmethod
    def send_error_alert(error_message):
        """Send alert if something breaks"""
        print(f"\n[{Alerter._time()}] Sending error alert...")
        
        subject = f"[ERROR] Trading Bot Failed - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        body = f"""
TRADING BOT ERROR
{datetime.now().strftime('%Y-%m-%d %H:%M UTC')}

Error:
{error_message}

Check GitHub Actions logs for details.
"""
        
        try:
            server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
            server.login(GMAIL_SENDER, GMAIL_PASSWORD)
            
            msg = MIMEMultipart()
            msg['From'] = GMAIL_SENDER
            msg['To'] = GMAIL_SENDER
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))
            
            server.send_message(msg)
            server.quit()
            
        except:
            pass
    
    @staticmethod
    def _time():
        return datetime.now().strftime('%H:%M')


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("="*70)
    print("AUTOMATED TRADING BOT - Alpaca Paper Trading")
    print("="*70)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Screening: {', '.join(TICKERS)}")
    print(f"Environment: Paper Trading (no real money)")
    print()
    
    try:
        # Initialize clients
        alpaca = AlpacaClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
        scanner = SignalScanner()
        trader = AutoTrader(alpaca)
        
        # Check API connection
        account = alpaca.get_account()
        print(f"✓ Connected to Alpaca")
        print(f"  Account Equity: ${float(account.equity):,.2f}")
        print()
        
        # Scan for signals
        data = scanner.load_data(TICKERS)
        scanner.scan_for_signals(data)
        
        # Execute trades
        executed = trader.execute_signals(scanner.signals)
        
        # Send alerts
        Alerter.send_execution_alert(executed, account)
        
        # Summary
        print()
        print("="*70)
        print("COMPLETE")
        print("="*70)
        print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
        
        if executed:
            print(f"✓ {len(executed)} position(s) entered")
        else:
            print("✗ No signals executed")
        
    except Exception as e:
        error_msg = str(e)
        print(f"\n✗ ERROR: {error_msg}")
        Alerter.send_error_alert(error_msg)


if __name__ == "__main__":
    main()
