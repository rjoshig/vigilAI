"""The frozen one-page report and its PDF (ADR-005: rendered once, never regenerated)."""

from greenlight_ai.report.render import RenderedReport, render_report, verdict_for, write_report

__all__ = ["RenderedReport", "render_report", "verdict_for", "write_report"]
