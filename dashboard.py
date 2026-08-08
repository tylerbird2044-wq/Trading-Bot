"""
ALPACA TRADING DASHBOARD
========================

Pulls all trades from Alpaca and generates an interactive HTML dashboard.

Usage:
1. Set environment variables (API keys)
2. Run: python dashboard.py
3. Open: dashboard.html in your browser

Or deploy to GitHub Actions to run daily.
"""

import os
import json
from datetime import datetime
import numpy as np
from alpaca.trading.client import TradingClient
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# CONFIGURATION
# ============================================================================

ALPACA_API_KEY = os.environ.get('ALPACA_API_KEY')
ALPACA_SECRET_KEY = os.environ.get('ALPACA_SECRET_KEY')

# ============================================================================
# FETCH TRADES
# ============================================================================

class TradeAnalyzer:
    def __init__(self, api_key, secret_key):
        self.client = TradingClient(api_key, secret_key, paper=True)
    
    def get_closed_trades(self):
        """Get all closed positions/trades from Alpaca"""
        try:
            # Get all activities
            activities = self.client.get_activities()
            
            trades = []
            
            for activity in activities:
                # Look for fill activities (executed orders)
                if hasattr(activity, 'activity_type') and 'fill' in str(activity.activity_type).lower():
                    trades.append({
                        'symbol': activity.symbol if hasattr(activity, 'symbol') else 'N/A',
                        'qty': activity.qty if hasattr(activity, 'qty') else 0,
                        'price': float(activity.price) if hasattr(activity, 'price') else 0,
                        'side': activity.side if hasattr(activity, 'side') else 'N/A',
                        'timestamp': activity.timestamp if hasattr(activity, 'timestamp') else '',
                    })
            
            return trades
        
        except Exception as e:
            print(f"Error fetching trades: {e}")
            return []
    
    def parse_trades_into_positions(self, trades):
        """Convert buy/sell fills into complete round-trip trades"""
        positions = {}
        completed_trades = []
        
        # Sort trades by timestamp
        trades_sorted = sorted(trades, key=lambda x: x['timestamp'])
        
        for trade in trades_sorted:
            symbol = trade['symbol']
            
            if symbol not in positions:
                positions[symbol] = []
            
            positions[symbol].append(trade)
            
            # If we have both buy and sell, complete the trade
            buys = [t for t in positions[symbol] if t['side'] == 'buy']
            sells = [t for t in positions[symbol] if t['side'] == 'sell']
            
            if buys and sells:
                buy_trade = buys[0]
                sell_trade = sells[0]
                
                entry_price = buy_trade['price']
                exit_price = sell_trade['price']
                shares = buy_trade['qty']
                
                pnl = (exit_price - entry_price) * shares
                pnl_pct = ((exit_price - entry_price) / entry_price) * 100
                
                try:
                    entry_time = datetime.fromisoformat(str(buy_trade['timestamp']).replace('Z', '+00:00'))
                    exit_time = datetime.fromisoformat(str(sell_trade['timestamp']).replace('Z', '+00:00'))
                    days_held = (exit_time - entry_time).days
                except:
                    days_held = 0
                
                completed_trades.append({
                    'symbol': symbol,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'shares': shares,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'entry_time': str(buy_trade['timestamp']),
                    'exit_time': str(sell_trade['timestamp']),
                    'days_held': days_held,
                    'is_win': pnl > 0,
                })
                
                # Remove completed trades from positions
                positions[symbol].remove(buy_trade)
                positions[symbol].remove(sell_trade)
        
        return completed_trades
    
    def calculate_metrics(self, trades):
        """Calculate trading metrics"""
        if not trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'total_pnl_pct': 0,
                'avg_winner': 0,
                'avg_loser': 0,
                'profit_factor': 0,
                'max_drawdown': 0,
                'sharpe_ratio': 0,
                'avg_bars_held': 0,
            }
        
        pnls = [t['pnl'] for t in trades]
        pnl_pcts = [t['pnl_pct'] for t in trades]
        
        wins = [t for t in trades if t['is_win']]
        losses = [t for t in trades if not t['is_win']]
        
        total_trades = len(trades)
        winning_trades = len(wins)
        losing_trades = len(losses)
        
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        total_pnl = sum(pnls)
        total_pnl_pct = (total_pnl / 100000) * 100
        
        avg_winner = sum([t['pnl'] for t in wins]) / len(wins) if wins else 0
        avg_loser = sum([t['pnl'] for t in losses]) / len(losses) if losses else 0
        
        gross_profit = sum([t['pnl'] for t in wins])
        gross_loss = abs(sum([t['pnl'] for t in losses]))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0
        
        # Max drawdown
        cumulative = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / np.maximum(running_max, 1)
        max_drawdown = np.min(drawdown) * 100 if len(drawdown) > 0 else 0
        
        # Sharpe ratio
        if len(pnl_pcts) > 1:
            returns = np.array(pnl_pcts)
            sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(252) if np.std(returns) > 0 else 0
        else:
            sharpe = 0
        
        # Average bars held
        avg_bars_held = np.mean([t['days_held'] for t in trades]) if trades else 0
        
        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'total_pnl_pct': total_pnl_pct,
            'avg_winner': avg_winner,
            'avg_loser': avg_loser,
            'profit_factor': profit_factor,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe,
            'avg_bars_held': avg_bars_held,
        }

# ============================================================================
# GENERATE HTML DASHBOARD
# ============================================================================

def generate_html_dashboard(trades, metrics):
    """Generate beautiful HTML dashboard"""
    
    winning_trades = len([t for t in trades if t['is_win']])
    losing_trades = len([t for t in trades if not t['is_win']])
    
    trades_html = ""
    for trade in sorted(trades, key=lambda x: x['entry_time'], reverse=True)[:50]:
        win_loss = "WIN" if trade['is_win'] else "LOSS"
        win_class = "win" if trade['is_win'] else "loss"
        pnl_color = "#2ecc71" if trade['is_win'] else "#e74c3c"
        
        trades_html += f"""
        <tr class="{win_class}">
            <td>{trade['symbol']}</td>
            <td>${trade['entry_price']:.2f}</td>
            <td>${trade['exit_price']:.2f}</td>
            <td>{trade['shares']}</td>
            <td style="color: {pnl_color}; font-weight: bold;">${trade['pnl']:,.2f}</td>
            <td style="color: {pnl_color}; font-weight: bold;">{trade['pnl_pct']:.2f}%</td>
            <td>{trade['days_held']}</td>
            <td class="badge {win_class}">{win_loss}</td>
            <td>{trade['entry_time'][:10]}</td>
        </tr>
        """
    
    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            color: #333;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        
        .header {{
            background: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            text-align: center;
        }}
        
        .header h1 {{
            font-size: 32px;
            margin-bottom: 10px;
            color: #667eea;
        }}
        
        .last-updated {{
            color: #999;
            font-size: 14px;
        }}
        
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        
        .metric-card {{
            background: white;
            padding: 25px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            text-align: center;
            transition: transform 0.3s;
        }}
        
        .metric-card:hover {{
            transform: translateY(-5px);
        }}
        
        .metric-label {{
            font-size: 14px;
            color: #999;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        
        .metric-value {{
            font-size: 32px;
            font-weight: bold;
            color: #667eea;
        }}
        
        .metric-value.positive {{
            color: #2ecc71;
        }}
        
        .metric-value.negative {{
            color: #e74c3c;
        }}
        
        .charts-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        
        .chart-card {{
            background: white;
            padding: 25px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        
        .chart-title {{
            font-size: 18px;
            font-weight: bold;
            margin-bottom: 15px;
            color: #333;
        }}
        
        .trades-table {{
            background: white;
            padding: 25px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            overflow-x: auto;
            margin-bottom: 20px;
        }}
        
        .trades-table h2 {{
            font-size: 20px;
            margin-bottom: 15px;
            color: #333;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        
        th {{
            background: #f5f5f5;
            padding: 12px;
            text-align: left;
            font-weight: bold;
            color: #333;
            border-bottom: 2px solid #ddd;
        }}
        
        td {{
            padding: 12px;
            border-bottom: 1px solid #eee;
        }}
        
        tr.win {{
            background: #f0fdf4;
        }}
        
        tr.loss {{
            background: #fef2f2;
        }}
        
        .badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
            color: white;
        }}
        
        .badge.win {{
            background: #2ecc71;
        }}
        
        .badge.loss {{
            background: #e74c3c;
        }}
        
        .footer {{
            text-align: center;
            color: white;
            margin-top: 30px;
            font-size: 14px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 Trading Dashboard</h1>
            <p class="last-updated">Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
        </div>
        
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-label">Total Trades</div>
                <div class="metric-value">{metrics['total_trades']}</div>
            </div>
            
            <div class="metric-card">
                <div class="metric-label">Win Rate</div>
                <div class="metric-value positive">{metrics['win_rate']:.1f}%</div>
            </div>
            
            <div class="metric-card">
                <div class="metric-label">Profit Factor</div>
                <div class="metric-value positive">{metrics['profit_factor']:.2f}:1</div>
            </div>
            
            <div class="metric-card">
                <div class="metric-label">Total P&L</div>
                <div class="metric-value {'positive' if metrics['total_pnl'] >= 0 else 'negative'}">${metrics['total_pnl']:,.0f}</div>
            </div>
            
            <div class="metric-card">
                <div class="metric-label">Avg Winner</div>
                <div class="metric-value positive">${metrics['avg_winner']:.0f}</div>
            </div>
            
            <div class="metric-card">
                <div class="metric-label">Avg Loser</div>
                <div class="metric-value negative">${metrics['avg_loser']:.0f}</div>
            </div>
            
            <div class="metric-card">
                <div class="metric-label">Sharpe Ratio</div>
                <div class="metric-value">{metrics['sharpe_ratio']:.2f}</div>
            </div>
            
            <div class="metric-card">
                <div class="metric-label">Max Drawdown</div>
                <div class="metric-value negative">{metrics['max_drawdown']:.2f}%</div>
            </div>
        </div>
        
        <div class="charts-grid">
            <div class="chart-card">
                <div class="chart-title">Win/Loss Distribution</div>
                <canvas id="winLossChart"></canvas>
            </div>
            
            <div class="chart-card">
                <div class="chart-title">P&L by Trade</div>
                <canvas id="pnlChart"></canvas>
            </div>
        </div>
        
        <div class="trades-table">
            <h2>Recent Trades (Last 50)</h2>
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Entry</th>
                        <th>Exit</th>
                        <th>Shares</th>
                        <th>P&L</th>
                        <th>P&L %</th>
                        <th>Days</th>
                        <th>Status</th>
                        <th>Date</th>
                    </tr>
                </thead>
                <tbody>
                    {trades_html if trades_html else '<tr><td colspan="9" style="text-align: center; color: #999;">No trades yet</td></tr>'}
                </tbody>
            </table>
        </div>
        
        <div class="footer">
            <p>Trading Dashboard • Auto-generated from Alpaca API • Paper Trading</p>
        </div>
    </div>
    
    <script>
        // Win/Loss Chart
        const winLossCtx = document.getElementById('winLossChart').getContext('2d');
        new Chart(winLossCtx, {{
            type: 'doughnut',
            data: {{
                labels: ['Wins', 'Losses'],
                datasets: [{{
                    data: [{winning_trades}, {losing_trades}],
                    backgroundColor: ['#2ecc71', '#e74c3c'],
                    borderColor: ['#27ae60', '#c0392b'],
                    borderWidth: 2
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{
                        position: 'bottom'
                    }}
                }}
            }}
        }});
        
        // P&L Chart (placeholder - will show "No trades yet")
        const pnlCtx = document.getElementById('pnlChart').getContext('2d');
        new Chart(pnlCtx, {{
            type: 'bar',
            data: {{
                labels: ['Trade Data Coming Soon...'],
                datasets: [{{
                    label: 'P&L per Trade',
                    data: [0],
                    backgroundColor: '#667eea',
                    borderRadius: 4
                }}]
            }},
            options: {{
                responsive: true,
                indexAxis: 'x',
                plugins: {{
                    legend: {{
                        display: true
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""
    
    return html

# ============================================================================
# MAIN
# ============================================================================

def main():
    print("="*70)
    print("ALPACA TRADING DASHBOARD")
    print("="*70)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    
    try:
        # Initialize analyzer
        analyzer = TradeAnalyzer(ALPACA_API_KEY, ALPACA_SECRET_KEY)
        
        # Get trades
        print("\n[*] Fetching trades from Alpaca...")
        raw_trades = analyzer.get_closed_trades()
        print(f"  ✓ Found {len(raw_trades)} trade fills")
        
        # Parse into complete trades
        print("[*] Parsing trades...")
        trades = analyzer.parse_trades_into_positions(raw_trades)
        print(f"  ✓ {len(trades)} complete round-trip trades")
        
        # Calculate metrics
        print("[*] Calculating metrics...")
        metrics = analyzer.calculate_metrics(trades)
        print(f"  ✓ Win Rate: {metrics['win_rate']:.1f}%")
        print(f"  ✓ Profit Factor: {metrics['profit_factor']:.2f}:1")
        print(f"  ✓ Total P&L: ${metrics['total_pnl']:,.0f}")
        
        # Generate HTML
        print("[*] Generating dashboard...")
        html = generate_html_dashboard(trades, metrics)
        
        # Save to file
        with open('dashboard.html', 'w') as f:
            f.write(html)
        
        print(f"  ✓ Dashboard saved to dashboard.html")
        
        print("\n" + "="*70)
        print("COMPLETE")
        print("="*70)
        print(f"Dashboard ready: Open dashboard.html in your browser")
        print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
