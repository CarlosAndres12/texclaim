"""Browser end-to-end tests of the web app (Playwright, Chromium, demo verifier, offline).

Run with `make e2e` (needs the built UI and `playwright install chromium`).
"""

from __future__ import annotations

import io
import re
import shutil
import socket
import threading
import time
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import Page, expect  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "texclaim" / "web" / "static" / "index.html"
EXAMPLES = ROOT / "examples"

pytestmark = pytest.mark.skipif(not STATIC.exists(), reason="web UI not built (make web)")

SOURCES = {
    "vaswani2017attention": [
        "Attention Is All You Need. Ashish Vaswani, Noam Shazeer.",
        "On the WMT 2014 English-to-German translation task, the big transformer model achieves a "
        "BLEU score of 28.4. Training took 3.5 days on 8 P100 GPUs. On English-to-French we reach "
        "41.8 BLEU.",
    ],
    "he2016deep": [
        "Deep Residual Learning for Image Recognition. Kaiming He, Xiangyu Zhang.",
        "We evaluate residual nets with a depth of up to 152 layers. An ensemble of these residual "
        "nets achieves 3.57% error on the ImageNet test set. This result won the 1st place on the "
        "ILSVRC 2015 classification task.",
    ],
    "devlin2019bert": [
        "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding.",
        "BERT obtains a GLUE score of 80.5, a 7.7 point absolute improvement. BERT large has 340M "
        "parameters.",
    ],
    "kingma2015adam": [
        "Adam: A Method for Stochastic Optimization. Diederik P. Kingma, Jimmy Ba.",
        "The method is straightforward to implement, is computationally efficient, and has little "
        "memory requirements. Good default settings are alpha 0.001, beta1 0.9 and beta2 0.999.",
    ],
    "ioffe2015batch": [
        "Batch Normalization: Accelerating Deep Network Training by Reducing Internal Covariate "
        "Shift. Sergey Ioffe, Christian Szegedy.",
        "Batch Normalization achieves the same accuracy with 14 times fewer training steps.",
    ],
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import os

    import uvicorn

    from texclaim.web.app import create_app
    from texclaim.web.projects import ProjectStore

    root = tmp_path_factory.mktemp("web")
    os.environ["TEXCLAIM_CACHE_DIR"] = str(root / "cache")
    os.environ["TEXCLAIM_CONFIG_DIR"] = str(root / "config")
    os.environ["TEXCLAIM_NO_DOTENV"] = "1"
    os.environ.pop("TEXCLAIM_MODEL", None)
    port = _free_port()
    app = create_app(ProjectStore(root / "data"))
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(timeout=5)


@pytest.fixture(autouse=True)
def isolated_dirs():  # override the unit-test fixture: the server owns its directories
    yield


def _latex_zip() -> bytes:
    from fixtures.make_pdfs import make_pdf

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in (EXAMPLES / "latex").iterdir():
            if f.is_file():
                z.write(f, f.name)
        for key, pages in SOURCES.items():
            filler = " This page continues with more detail on the experimental setup." * 6
            z.writestr(f"papers/{key}.pdf", make_pdf([pg + filler for pg in pages]))
    return buf.getvalue()


def _create_latex_project(base: str) -> str:
    import httpx

    r = httpx.post(
        f"{base}/api/projects",
        data={"name": "LaTeX example"},
        files={"files": ("latex.zip", _latex_zip(), "application/zip")},
    )
    r.raise_for_status()
    return r.json()["id"]


def test_home_and_language(server, page: Page):
    page.goto(server + "/?lang=en")
    expect(page.get_by_role("heading", name="Your projects")).to_be_visible()
    page.get_by_test_id("lang-es").click()
    expect(page.get_by_role("heading", name="Sus proyectos")).to_be_visible()
    expect(page.locator("html")).to_have_attribute("lang", "es")
    page.goto(server + "/")  # the choice persists (no ?lang override)
    expect(page.get_by_role("heading", name="Sus proyectos")).to_be_visible()
    page.get_by_test_id("lang-en").click()


def test_create_markdown_project_via_dialog(server, page: Page, tmp_path):
    page.goto(server + "/?lang=en")
    page.get_by_test_id("new-project").click()
    page.get_by_label("Project name").fill("Spanish markdown")
    src = EXAMPLES / "markdown"
    page.get_by_test_id("file-input").set_input_files(
        [str(src / "articulo.md"), str(src / "refs.bib")]
    )
    expect(page.get_by_text("2 files selected")).to_be_visible()
    page.get_by_test_id("create-project").click()
    expect(page).to_have_url(re.compile(r"/settings"))
    expect(page.get_by_text("Introducción").first).to_be_visible()
    page.get_by_test_id("tab-overview").click()
    expect(page.get_by_text("markdown", exact=True)).to_be_visible()


def test_full_check_flow(server, page: Page):
    pid = _create_latex_project(server)
    page.goto(f"{server}/projects/{pid}/settings?lang=en")
    page.get_by_role("combobox", name="Model").click()
    page.get_by_role("option", name="demo", exact=True).click()
    page.get_by_test_id("scope-two").click()
    page.get_by_role("switch", name="Offline (do not download sources)").click()
    expect(page.get_by_test_id("save-settings")).to_have_text("Saved")  # auto-saved

    page.get_by_test_id("start-run").click()
    expect(page.get_by_test_id("run-state")).to_have_attribute("data-state", "done", timeout=60_000)
    expect(page.get_by_test_id("run-log")).to_contain_text("Check finished")

    page.get_by_test_id("view-results").click()
    page.get_by_test_id("flagged-only").click()  # show all checks
    items = page.get_by_test_id("findings-list").locator("li button")
    expect(items.first).to_be_visible()
    assert items.count() >= 10
    # Pick a cited, supported unit with a PDF and check the viewer renders the page
    page.get_by_test_id("origin-cited").click()
    page.get_by_test_id("findings-search").fill("28.4")
    items.first.click()
    detail = page.get_by_test_id("finding-detail")
    expect(detail).to_contain_text("vaswani2017attention")
    viewer = page.get_by_test_id("pdf-viewer")
    if viewer.count():
        expect(viewer.locator("canvas")).to_be_visible(timeout=15_000)

    # Internal claims: the conclusions are listed
    page.get_by_test_id("findings-search").fill("")
    page.get_by_test_id("origin-conclusions").click()
    expect(page.get_by_test_id("findings-list")).to_contain_text("5 points")

    # Document view highlights claim lines
    page.get_by_test_id("tab-document").click()
    expect(page.get_by_test_id("document-view").locator("[data-verdict]").first).to_be_visible()

    # Sources table and the PDF dialog
    page.get_by_test_id("tab-sources").click()
    expect(page.get_by_test_id("sources-table")).to_contain_text("Attention Is All You Need")
    page.get_by_test_id("view-he2016deep").click()
    expect(page.get_by_role("dialog").locator("canvas")).to_be_visible(timeout=15_000)
    page.keyboard.press("Escape")

    # Knowledge graph renders and search focuses a node
    page.get_by_test_id("tab-graph").click()
    expect(page.get_by_test_id("graph-canvas").locator("canvas").first).to_be_visible()
    page.get_by_test_id("graph-search").fill("accuracy")
    page.locator("ul >> text=accuracy").first.click()
    expect(page.get_by_test_id("graph-panel")).to_contain_text("accuracy")

    # Downloads
    page.get_by_test_id("tab-overview").click()
    with page.expect_download() as d:
        page.get_by_test_id("download-docx").click()
    assert d.value.suggested_filename.endswith(".docx")

    # Spanish UI on the same project
    page.get_by_test_id("lang-es").click()
    expect(page.get_by_test_id("tab-findings")).to_contain_text("Hallazgos")
    page.get_by_test_id("lang-en").click()


def test_word_project_outline(server, page: Page):
    import httpx

    data = (EXAMPLES / "word" / "paper.docx").read_bytes()
    r = httpx.post(
        f"{server}/api/projects",
        files={"files": ("paper.docx", data, "application/octet-stream")},
    )
    pid = r.json()["id"]
    page.goto(f"{server}/projects/{pid}?lang=en")
    expect(page.get_by_text("docx", exact=True)).to_be_visible()
    expect(page.get_by_text("4 cited claims").or_(page.get_by_text("cited claims"))).to_be_visible()
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc missing")


def test_not_found_page(server, page: Page):
    page.goto(server + "/nowhere?lang=en")
    expect(page.get_by_text("Page not found")).to_be_visible()
    page.goto(server + "/projects/doesnotexist?lang=en")
    expect(page.get_by_text("Page not found")).to_be_visible()


def test_unsaved_settings_apply_to_the_run(server, page: Page):
    pid = _create_latex_project(server)
    page.goto(f"{server}/projects/{pid}/settings?lang=en")
    page.get_by_role("switch", name="Offline (do not download sources)").click()
    page.get_by_role("combobox", name="Model").click()
    page.get_by_role("option", name="demo", exact=True).click()
    page.get_by_test_id("start-run").click()  # immediately, before the auto-save delay
    expect(page.get_by_test_id("run-log")).to_contain_text("model demo", timeout=20_000)


def test_no_horizontal_overflow(server, page: Page):
    pid = _create_latex_project(server)
    import httpx

    httpx.put(f"{server}/api/projects/{pid}/settings", json={"model": "demo", "offline": True})
    httpx.post(f"{server}/api/projects/{pid}/runs", json={})
    for _ in range(100):
        if httpx.get(f"{server}/api/projects/{pid}/runs/current").json()["state"] != "running":
            break
        time.sleep(0.2)
    for width in (1440, 390):
        page.set_viewport_size({"width": width, "height": 900})
        for tab in ("", "run", "findings", "document", "sources", "graph", "settings"):
            page.goto(f"{server}/projects/{pid}/{tab}?lang=en")
            page.wait_for_timeout(700)
            sw = page.evaluate("document.documentElement.scrollWidth")
            assert sw <= width + 1, f"{tab or 'overview'} at {width}px is {sw}px wide"


def test_recheck_everything_asks_first(server, page: Page):
    import httpx

    pid = _create_latex_project(server)
    httpx.put(f"{server}/api/projects/{pid}/settings", json={"model": "demo", "offline": True})
    httpx.post(f"{server}/api/projects/{pid}/runs", json={})
    for _ in range(100):
        if httpx.get(f"{server}/api/projects/{pid}/runs/current").json()["state"] != "running":
            break
        time.sleep(0.2)
    page.goto(f"{server}/projects/{pid}/run?lang=en")
    page.get_by_test_id("recheck-all").click()
    expect(page.get_by_role("dialog")).to_contain_text("Re-check everything?")
    page.get_by_role("button", name="Cancel").click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    page.get_by_test_id("run-start").click()  # estimate wording is checked via a dry run below
    expect(page.get_by_test_id("run-state")).to_have_attribute("data-state", "done", timeout=30_000)
    page.get_by_role("button", name="Estimate (dry run)").click()
    expect(page.get_by_test_id("run-state")).to_contain_text("Estimate finished", timeout=30_000)
