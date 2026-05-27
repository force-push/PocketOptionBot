"""Rich terminal dashboard for live monitoring."""

from datetime import datetime

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class Dashboard:
    """Live updating terminal UI."""

    def __init__(self):
        self.console = Console()
        self.last_trades = []
        self.signal_evals = []
        self.daily_pnl = 0.0
        self.trade_count = 0

    def update(
        self,
        asset: str,
        price: float,
        countdown: int,
        balance: float,
        is_demo: bool,
        last_signal_result,
        last_trade_result,
        risk_status: str = "OK",
    ):
        """Update and redraw dashboard."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=3),
        )

        # Header
        mode_str = "🟢 DEMO" if is_demo else "🔴 LIVE"
        header_text = Text(
            f"{asset} @ {price:.5f} | Timer: {countdown}s | Balance: ${balance:.2f} | {mode_str}",
            style="bold cyan",
        )
        layout["header"].update(Panel(header_text))

        # Main: signals + trades
        layout["main"].split_row(
            Layout(name="signals"),
            Layout(name="trades"),
        )

        # Signals panel
        sig_table = Table(title="Signal Evals")
        sig_table.add_column("Signal", style="cyan")
        sig_table.add_column("Direction", style="magenta")
        sig_table.add_column("Conf", style="yellow")
        for sig in self.signal_evals[-5:]:
            sig_table.add_row(sig[0], sig[1] or "—", f"{sig[2]:.2f}")
        layout["signals"].update(Panel(sig_table, title="Signals"))

        # Trades panel
        trade_table = Table(title="Trades")
        trade_table.add_column("ID", style="cyan")
        trade_table.add_column("Dir", style="magenta")
        trade_table.add_column("Result", style="green")
        for trade in self.last_trades[-5:]:
            trade_table.add_row(trade[0], trade[1], trade[2])
        layout["trades"].update(Panel(trade_table, title="Recent Trades"))

        # Footer
        footer_text = Text(
            f"P&L: {self.daily_pnl:+.2f} | Trades: {self.trade_count} | Status: {risk_status}",
            style="bold",
        )
        layout["footer"].update(Panel(footer_text))

        self.console.clear()
        self.console.print(layout)

    def log_trade(self, trade_id: str, direction: str, result: str):
        self.last_trades.append((trade_id, direction, result))

    def log_signal(self, name: str, direction: str, confidence: float):
        self.signal_evals.append((name, direction, confidence))
