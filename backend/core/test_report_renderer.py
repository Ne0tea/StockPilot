from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import report_renderer


def test_build_report_instruction_target_returns_absolute_backend_path(tmp_path, monkeypatch):
    reports_root = tmp_path / "reports"
    monkeypatch.setattr(report_renderer, "REPORTS_DIR", str(reports_root))

    target = report_renderer.build_report_instruction_target("002129", date(2026, 6, 11))

    assert Path(target).is_absolute()
    assert target == str(reports_root / "002129" / "2026-06-11.html")


def test_move_generated_report_html_migrates_home_relative_agent_output(tmp_path, monkeypatch):
    reports_root = tmp_path / "reports"
    home_root = tmp_path / "home"
    source = home_root / "002129" / "2026-06-11.html"
    source.parent.mkdir(parents=True)
    source.write_text("<html><body>report</body></html>", encoding="utf-8")

    monkeypatch.setattr(report_renderer, "REPORTS_DIR", str(reports_root))
    monkeypatch.setenv("HOME", str(home_root))

    relative_path = report_renderer.move_generated_report_html("002129", date(2026, 6, 11))

    destination = reports_root / "002129" / "2026-06-11.html"
    assert relative_path == "reports/002129/2026-06-11.html"
    assert destination.read_text(encoding="utf-8") == "<html><body>report</body></html>"
    assert not source.exists()
