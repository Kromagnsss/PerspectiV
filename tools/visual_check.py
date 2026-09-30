from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "http://127.0.0.1:8501"
DEFAULT_OUT = ROOT / "reports" / "visual_checks"
VIEWPORT = {"width": 1920, "height": 1080}

BROWSER_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
]

PAGES = [
    {
        "slug": "dashboard",
        "nav": re.compile(r"Tableau de bord", re.I),
        "header": '[class*="st-key-pv_sticky_header_dashboard"]',
        "content": "Projets",
    },
    {
        "slug": "projects",
        "nav": re.compile(r"Projets", re.I),
        "header": '[class*="st-key-pv_sticky_header_projects"]',
        "content": "Gantt projets",
    },
    {
        "slug": "tasks",
        "nav": re.compile(r"T.*ches et Gantt", re.I),
        "header": '[class*="st-key-pv_sticky_header_tasks"]',
        "content": "Gantt t\u00e2ches",
    },
    {
        "slug": "timesheet",
        "nav": re.compile(r"Timesheet", re.I),
        "header": '[class*="st-key-pv_sticky_header_timesheet"]',
        "content": "Saisie hebdomadaire",
        "right_arrow": True,
        "dropdown_index": 1,
    },
    {
        "slug": "planning",
        "nav": re.compile(r"Planification", re.I),
        "header": '[class*="st-key-pv_sticky_header_planning"]',
        "content": "Saisie hebdomadaire",
        "right_arrow": True,
        "dropdown_index": 1,
    },
    {
        "slug": "risks",
        "nav": re.compile(r"Gestion des risques", re.I),
        "header": '[class*="st-key-pv_sticky_header_risks"]',
        "content": "Matrice des risques",
        "dropdown_index": 1,
    },
]


class VisualReport:
    def __init__(self, out_dir: Path, url: str, browser_executable: Path):
        self.out_dir = out_dir
        self.url = url
        self.browser_executable = browser_executable
        self.checks: list[dict[str, Any]] = []
        self.captures: dict[str, str] = {}

    def check(self, name: str, ok: bool, details: dict[str, Any] | None = None) -> None:
        self.checks.append({"name": name, "ok": ok, "details": details or {}})

    def capture(self, key: str, path: Path) -> None:
        self.captures[key] = str(path.relative_to(ROOT))

    @property
    def ok(self) -> bool:
        return all(item["ok"] for item in self.checks)

    def write(self) -> Path:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "url": self.url,
            "viewport": VIEWPORT,
            "browser_executable": str(self.browser_executable),
            "ok": self.ok,
            "checks": self.checks,
            "captures": self.captures,
        }
        report_path = self.out_dir / "visual_report.json"
        report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return report_path


def wait_for_server(url: str, timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.status < 500
        except Exception:
            time.sleep(0.5)
    return False


def browser_executable(explicit_path: str | None) -> Path:
    if explicit_path:
        path = Path(explicit_path)
        if path.exists():
            return path
        raise FileNotFoundError(f"Browser executable not found: {path}")
    for path in BROWSER_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError("No Edge or Chrome executable found.")


def safe_filename(slug: str, suffix: str) -> str:
    return f"{slug}_1920_{suffix}.png"


def box_right(box: dict[str, float]) -> float:
    return float(box["x"]) + float(box["width"])


def box_bottom(box: dict[str, float]) -> float:
    return float(box["y"]) + float(box["height"])


def login(page, url: str, username: str, password: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(1000)
    button = page.get_by_role("button", name=re.compile(r"Se connecter", re.I)).first
    try:
        button.wait_for(state="visible", timeout=15000)
        page.get_by_label("Utilisateur").fill(username)
        page.get_by_label("Mot de passe").fill(password)
        button.click()
        button.wait_for(state="hidden", timeout=20000)
    except PlaywrightTimeoutError:
        pass
    page.locator('[class*="st-key-pv_sticky_header_dashboard"]').first.wait_for(state="visible", timeout=20000)
    page.wait_for_timeout(1200)


def navigate(page, nav_pattern: re.Pattern[str], header_selector: str | None = None) -> None:
    if header_selector and page.locator(header_selector).first.is_visible(timeout=1000):
        return
    button = page.get_by_role("button", name=nav_pattern).first
    if button.count() > 0:
        button.click(timeout=10000)
    else:
        buttons = page.locator("button")
        texts = []
        clicked = False
        for index in range(buttons.count()):
            current = buttons.nth(index)
            text = current.inner_text(timeout=1000).strip()
            texts.append(text)
            if nav_pattern.search(text):
                current.click(timeout=10000)
                clicked = True
                break
        if not clicked:
            raise RuntimeError(f"Navigation button not found for {nav_pattern.pattern}. Buttons: {texts}")
    page.wait_for_timeout(2200)
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except PlaywrightTimeoutError:
        pass


def visible_box(locator) -> dict[str, float] | None:
    try:
        if not locator.is_visible(timeout=3000):
            return None
        return locator.bounding_box()
    except PlaywrightTimeoutError:
        return None


def last_visible_box(locator) -> tuple[Any | None, dict[str, float] | None]:
    for index in range(locator.count() - 1, -1, -1):
        current = locator.nth(index)
        box = visible_box(current)
        if box:
            return current, box
    return None, None


def inspect_page(page, spec: dict[str, Any], report: VisualReport) -> None:
    slug = str(spec["slug"])
    navigate(page, spec["nav"], str(spec["header"]))

    full_path = report.out_dir / safe_filename(slug, "full")
    page.screenshot(path=str(full_path), full_page=False)
    report.capture(f"{slug}_full", full_path)

    header = page.locator(str(spec["header"])).first
    header.wait_for(state="visible", timeout=10000)
    header_path = report.out_dir / safe_filename(slug, "header")
    header.screenshot(path=str(header_path))
    report.capture(f"{slug}_header", header_path)

    header_box = visible_box(header)
    report.check(f"{slug}: header visible", header_box is not None, {"box": header_box})
    if header_box:
        report.check(
            f"{slug}: header inside viewport",
            header_box["x"] >= 0 and box_right(header_box) <= VIEWPORT["width"],
            {"box": header_box, "viewport": VIEWPORT},
        )

    content = page.get_by_text(str(spec["content"]), exact=False).first
    content_box = visible_box(content)
    report.check(f"{slug}: content anchor visible", content_box is not None, {"box": content_box})
    if header_box and content_box:
        report.check(
            f"{slug}: content starts below header",
            content_box["y"] >= box_bottom(header_box) - 2,
            {"header": header_box, "content": content_box},
        )

    if spec.get("right_arrow"):
        arrow = page.locator("button").filter(has_text="\u203a").first
        arrow_box = visible_box(arrow)
        report.check(f"{slug}: right week arrow visible", arrow_box is not None, {"box": arrow_box})
        if arrow_box:
            report.check(
                f"{slug}: right week arrow inside viewport",
                arrow_box["x"] >= 0 and box_right(arrow_box) <= VIEWPORT["width"] - 8,
                {"box": arrow_box, "viewport": VIEWPORT},
            )

    dropdown_index = spec.get("dropdown_index")
    if dropdown_index is not None:
        triggers = header.locator('[role="combobox"]')
        trigger = triggers.nth(int(dropdown_index)) if triggers.count() > int(dropdown_index) else None
        trigger_box = visible_box(trigger) if trigger is not None else None
        report.check(f"{slug}: dropdown trigger visible", trigger_box is not None, {"box": trigger_box})
        if trigger_box:
            trigger.click(timeout=5000)
            page.wait_for_timeout(600)
            dropdown_path = report.out_dir / safe_filename(slug, "dropdown")
            page.screenshot(path=str(dropdown_path), full_page=False)
            report.capture(f"{slug}_dropdown", dropdown_path)
            popover, popover_box = last_visible_box(
                page.locator('div[role="listbox"], div[data-baseweb="popover"], div[data-baseweb="menu"]')
            )
            z_index = None
            if popover is not None and popover_box:
                z_index = popover.evaluate("el => window.getComputedStyle(el).zIndex")
            popover_inside_viewport = (
                popover_box is not None
                and popover_box["x"] >= 0
                and box_right(popover_box) <= VIEWPORT["width"]
                and popover_box["y"] >= 0
                and box_bottom(popover_box) <= VIEWPORT["height"]
            )
            report.check(
                f"{slug}: dropdown visible above content",
                popover_inside_viewport and str(z_index) not in {"auto", "0", ""},
                {"box": popover_box, "z_index": z_index, "viewport": VIEWPORT},
            )
            page.keyboard.press("Escape")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture and assert PerspectiV visual layout at 1920x1080.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--browser-executable", default=None)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--server-timeout", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not wait_for_server(args.url, args.server_timeout):
        print(f"Server is not reachable: {args.url}", file=sys.stderr)
        return 2

    executable = browser_executable(args.browser_executable)
    report = VisualReport(out_dir, args.url, executable)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(executable),
            headless=True,
            args=["--disable-gpu", "--window-size=1920,1080"],
        )
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        page = context.new_page()
        login(page, args.url, args.username, args.password)
        for spec in PAGES:
            inspect_page(page, spec, report)
        context.close()
        browser.close()

    report_path = report.write()
    print(f"Visual report: {report_path}")
    for key, path in sorted(report.captures.items()):
        print(f"{key}: {path}")
    if not report.ok:
        failed = [item for item in report.checks if not item["ok"]]
        print("Failed visual checks:", file=sys.stderr)
        for item in failed:
            print(f"- {item['name']}: {item['details']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
