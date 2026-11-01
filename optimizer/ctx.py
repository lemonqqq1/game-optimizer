"""Общее состояние: режим dry-run и логгер."""
dry_run = False
_logger = print


def set_logger(fn):
    global _logger
    _logger = fn


def log(msg: str):
    _logger(msg)
