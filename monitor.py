import time
import platform
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from logger import logger, log_monitor_alert, log_error
from utils import now_iso, divider


try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False
    logger.warning("psutil not installed – using simulated metrics.")


# ─────────────────────────────────────────────────────────────
# THRESHOLDS
# ─────────────────────────────────────────────────────────────
THRESHOLDS: Dict[str, float] = {
    "cpu":    90.0,   # %
    "memory": 95.0,   # %
    "disk":   90.0,   # % used  (free < 10% → used > 90%)
    "network": 100.0, # Mbps (informational)
}


# ─────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────
@dataclass
class MetricSnapshot:
    """Immutable snapshot of system metrics at a point in time."""
    timestamp:     str
    cpu_percent:   float
    memory_percent: float
    disk_percent:  float
    disk_free_gb:  float
    net_sent_mbps: float
    net_recv_mbps: float

    def alerts(self) -> List[Tuple[str, float, float]]:
        """
        Return list of (metric_name, value, threshold) tuples
        for any metric that exceeds its threshold.
        """
        triggered = []
        if self.cpu_percent    > THRESHOLDS["cpu"]:
            triggered.append(("cpu",    self.cpu_percent,    THRESHOLDS["cpu"]))
        if self.memory_percent > THRESHOLDS["memory"]:
            triggered.append(("memory", self.memory_percent, THRESHOLDS["memory"]))
        if self.disk_percent   > THRESHOLDS["disk"]:
            triggered.append(("disk",   self.disk_percent,   THRESHOLDS["disk"]))
        net_total = self.net_sent_mbps + self.net_recv_mbps
        if net_total > THRESHOLDS["network"]:
            triggered.append(("network", net_total, THRESHOLDS["network"]))
        return triggered

    def to_dict(self) -> Dict:
        return {
            "timestamp":      self.timestamp,
            "cpu_percent":    self.cpu_percent,
            "memory_percent": self.memory_percent,
            "disk_percent":   self.disk_percent,
            "disk_free_gb":   round(self.disk_free_gb, 2),
            "net_sent_mbps":  round(self.net_sent_mbps, 2),
            "net_recv_mbps":  round(self.net_recv_mbps, 2),
        }

    def summary_line(self) -> str:
        return (
            f"[{self.timestamp}] "
            f"CPU={self.cpu_percent:.1f}% | "
            f"MEM={self.memory_percent:.1f}% | "
            f"DISK={self.disk_percent:.1f}% (free {self.disk_free_gb:.1f} GB) | "
            f"NET ↑{self.net_sent_mbps:.1f} ↓{self.net_recv_mbps:.1f} Mbps"
        )


# ─────────────────────────────────────────────────────────────
# MONITOR CLASS
# ─────────────────────────────────────────────────────────────
class Monitor:
    

    def __init__(self, ticket_manager=None, history_limit: int = 100):
        self._history: List[MetricSnapshot] = []
        self._history_limit = history_limit
        self._ticket_manager = ticket_manager   # injected dependency
        self._net_bytes_prev: Optional[Tuple[int, int]] = None
        self._net_time_prev:  Optional[float]  = None

    # ── Core Metric Collection ────────────────────────────────
    def collect(self) -> MetricSnapshot:
        """Collect one snapshot of system metrics."""
        try:
            if _PSUTIL_AVAILABLE:
                snap = self._collect_real()
            else:
                snap = self._collect_simulated()

            # Store in history (bounded)
            self._history.append(snap)
            if len(self._history) > self._history_limit:
                self._history.pop(0)

            # Check thresholds and act
            self._handle_alerts(snap)
            return snap

        except Exception as e:
            log_error("Monitor.collect", e)
            return self._collect_simulated()

    def _collect_real(self) -> MetricSnapshot:
        """Use psutil to gather live metrics."""
        cpu     = psutil.cpu_percent(interval=0.5)
        mem     = psutil.virtual_memory()
        disk    = psutil.disk_usage("/")
        net_now = psutil.net_io_counters()
        t_now   = time.time()

        # Network throughput (Mbps delta)
        sent_mbps = recv_mbps = 0.0
        if self._net_bytes_prev and self._net_time_prev:
            dt = t_now - self._net_time_prev
            if dt > 0:
                sent_mbps = (net_now.bytes_sent - self._net_bytes_prev[0]) / dt / 1e6 * 8
                recv_mbps = (net_now.bytes_recv - self._net_bytes_prev[1]) / dt / 1e6 * 8

        self._net_bytes_prev = (net_now.bytes_sent, net_now.bytes_recv)
        self._net_time_prev  = t_now

        return MetricSnapshot(
            timestamp=      now_iso(),
            cpu_percent=    cpu,
            memory_percent= mem.percent,
            disk_percent=   disk.percent,
            disk_free_gb=   disk.free / (1024 ** 3),
            net_sent_mbps=  sent_mbps,
            net_recv_mbps=  recv_mbps,
        )

    @staticmethod
    def _collect_simulated() -> MetricSnapshot:
        """Return mock metrics when psutil is unavailable (demo/testing)."""
        import random
        random.seed()
        return MetricSnapshot(
            timestamp=      now_iso(),
            cpu_percent=    random.uniform(10, 85),
            memory_percent= random.uniform(40, 80),
            disk_percent=   random.uniform(30, 75),
            disk_free_gb=   random.uniform(20, 200),
            net_sent_mbps=  random.uniform(0, 10),
            net_recv_mbps=  random.uniform(0, 10),
        )

    # ── Alert Handling ────────────────────────────────────────
    def _handle_alerts(self, snap: MetricSnapshot) -> None:
        for metric, value, threshold in snap.alerts():
            log_monitor_alert(metric, value, threshold)
            if self._ticket_manager:
                self._auto_create_ticket(metric, value)

    def _auto_create_ticket(self, metric: str, value: float) -> None:
        """Auto-create a P1 incident ticket for a threshold breach."""
        descriptions = {
            "cpu":    f"HIGH CPU ALERT – CPU usage at {value:.1f}% (threshold 90%)",
            "memory": f"HIGH MEMORY ALERT – RAM usage at {value:.1f}% (threshold 95%)",
            "disk":   f"LOW DISK SPACE ALERT – Disk {value:.1f}% full (free < 10%)",
            "network": f"HIGH NETWORK ALERT – Combined throughput at {value:.1f} Mbps (threshold 100 Mbps)",
        }
        desc = descriptions.get(metric, f"MONITORING ALERT: {metric}={value:.1f}%")
        try:
            ticket = self._ticket_manager.create_ticket(
                employee_name=    "System Monitor",
                department=       "IT Operations",
                issue_description= desc,
                category=         "Performance",
                priority=         "P1",
                ticket_type=      "Incident",
                impact=           "High",
                urgency=          "High",
            )
            logger.critical(
                f"AUTO-TICKET CREATED | id={ticket.ticket_id} | reason={metric} alert"
            )
        except Exception as e:
            log_error("Monitor._auto_create_ticket", e)

    # ── Continuous Monitoring ─────────────────────────────────
    def run_once(self) -> MetricSnapshot:
        """Collect and display a single snapshot."""
        snap = self.collect()
        print(snap.summary_line())
        alerts = snap.alerts()
        if alerts:
            print(f"  ⚠️  ALERTS: {[a[0] for a in alerts]}")
        return snap

    def metric_stream(self, interval_seconds: float = 5.0, count: int = 10):
        """
        Generator: yield MetricSnapshot every `interval_seconds`.
        Demonstrates Python generators.
        """
        collected = 0
        while collected < count:
            snap = self.collect()
            yield snap
            collected += 1
            if collected < count:
                time.sleep(interval_seconds)

    # ── History ───────────────────────────────────────────────
    def get_history(self) -> List[MetricSnapshot]:
        return list(self._history)

    def get_latest(self) -> Optional[MetricSnapshot]:
        return self._history[-1] if self._history else None

    def avg_cpu(self) -> float:
        if not self._history:
            return 0.0
        return sum(s.cpu_percent for s in self._history) / len(self._history)

    def avg_memory(self) -> float:
        if not self._history:
            return 0.0
        return sum(s.memory_percent for s in self._history) / len(self._history)

    # ── Static Utilities ──────────────────────────────────────
    @staticmethod
    def system_info() -> Dict:
        """Return static system information dict."""
        info = {
            "platform": platform.system(),
            "release":  platform.release(),
            "machine":  platform.machine(),
            "python":   platform.python_version(),
        }
        if _PSUTIL_AVAILABLE:
            info["cpu_count"]   = psutil.cpu_count(logical=True)
            mem = psutil.virtual_memory()
            info["total_ram_gb"] = round(mem.total / (1024 ** 3), 1)
        return info

    def display_dashboard(self) -> None:
        snap = self.collect()
        si   = self.system_info()
        print(divider("═"))
        print("  SYSTEM MONITOR DASHBOARD")
        print(divider("═"))
        print(f"  Platform : {si.get('platform')} {si.get('release')}")
        print(f"  CPU Cores: {si.get('cpu_count', 'N/A')}  |  RAM: {si.get('total_ram_gb', 'N/A')} GB")
        print(divider())
        print(f"  {snap.summary_line()}")
        alerts = snap.alerts()
        if alerts:
            for m, v, t in alerts:
                print(f"  ⚠️  ALERT: {m.upper()} = {v:.1f}% exceeds {t}%")
        else:
            print("  ✅ All metrics within normal range.")
        print(divider("═"))

    def __repr__(self):
        return f"Monitor(history={len(self._history)}, psutil={_PSUTIL_AVAILABLE})"
