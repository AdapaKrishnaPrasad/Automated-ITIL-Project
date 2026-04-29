import logging
import os
from datetime import datetime
from functools import wraps

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
LOG_FILE = os.path.join(os.path.dirname(__file__), "data", "logs.txt")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# ─────────────────────────────────────────────
# Custom Formatter
# ─────────────────────────────────────────────
class ITILFormatter(logging.Formatter):
    """Custom formatter that adds ITIL context to log messages."""

    LEVEL_ICONS = {
        "DEBUG":    "🔍",
        "INFO":     "✅",
        "WARNING":  "⚠️ ",
        "ERROR":    "❌",
        "CRITICAL": "🔥",
    }

    def format(self, record):
        icon = self.LEVEL_ICONS.get(record.levelname, "  ")
        record.icon = icon
        return super().format(record)


# ─────────────────────────────────────────────
# Logger Setup
# ─────────────────────────────────────────────
def get_logger(name: str = "ITServiceDesk") -> logging.Logger:
    """Return a configured logger. Creates handlers only once."""
    logger = logging.getLogger(name)

    if logger.handlers:          # avoid duplicate handlers on re-import
        return logger

    logger.setLevel(logging.DEBUG)

    fmt = "%(asctime)s | %(icon)s %(levelname)-8s | %(name)s | %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"
    formatter = ITILFormatter(fmt, datefmt=date_fmt)

    # File handler – keeps all levels
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)

    # Console handler – INFO and above
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# Shared application-wide logger instance
logger = get_logger()


# ─────────────────────────────────────────────
# Decorator Utilities
# ─────────────────────────────────────────────
def log_action(action_name: str):
    """Decorator factory: logs entry/exit/exception for any function."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger.debug(f"[START] {action_name} | args={args[1:]} kwargs={kwargs}")
            try:
                result = func(*args, **kwargs)
                logger.debug(f"[END]   {action_name} completed successfully")
                return result
            except Exception as exc:
                logger.error(f"[FAIL]  {action_name} raised {type(exc).__name__}: {exc}")
                raise
        return wrapper
    return decorator


def log_ticket_event(event: str, ticket_id: str, detail: str = ""):
    """Helper to log standardised ticket lifecycle events."""
    msg = f"TICKET_EVENT | event={event} | id={ticket_id}"
    if detail:
        msg += f" | {detail}"
    logger.info(msg)


def log_sla_breach(ticket_id: str, priority: str, breached_by_mins: float):
    logger.warning(
        f"SLA_BREACH | ticket={ticket_id} | priority={priority} | "
        f"overdue_by={breached_by_mins:.1f} min"
    )


def log_monitor_alert(metric: str, value: float, threshold: float):
    logger.critical(
        f"MONITOR_ALERT | metric={metric} | value={value:.1f}% | threshold={threshold}%"
    )


def log_error(context: str, error: Exception):
    logger.error(f"ERROR | context={context} | type={type(error).__name__} | msg={error}")
