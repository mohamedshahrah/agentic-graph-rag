"""The structured-text loaders (CSV, HTML) — content shaping, not parsing libs."""

from __future__ import annotations

from graphrag.ingestion.loaders.csv import CSVLoader
from graphrag.ingestion.loaders.html import HTMLLoader


def test_csv_rows_become_labeled_sentences(tmp_path):
    path = tmp_path / "products.csv"
    path.write_text("name,price\nWidget,12.50\nGadget,3.99\n", encoding="utf-8")
    doc = CSVLoader().load(path)
    assert "name: Widget; price: 12.50" in doc.content
    assert "name: Gadget; price: 3.99" in doc.content
    assert doc.metadata["rows"] == 2


def test_tsv_uses_tab_delimiter(tmp_path):
    path = tmp_path / "t.tsv"
    path.write_text("a\tb\n1\t2\n", encoding="utf-8")
    doc = CSVLoader().load(path)
    assert "a: 1; b: 2" in doc.content


def test_html_strips_scripts_and_keeps_title(tmp_path):
    path = tmp_path / "page.html"
    path.write_text(
        "<html><head><title>Quarterly Report</title><script>alert(1)</script></head>"
        "<body><nav>menu</nav><p>Revenue grew 40%.</p></body></html>",
        encoding="utf-8",
    )
    doc = HTMLLoader().load(path)
    assert "Quarterly Report" in doc.content
    assert "Revenue grew 40%." in doc.content
    assert "alert" not in doc.content
    assert "menu" not in doc.content  # nav chrome removed
