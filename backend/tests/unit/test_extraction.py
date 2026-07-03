from types import SimpleNamespace

import langchain_community.document_loaders

from app.rag.extraction import ExtractionQuality, extract_document, first_markdown_heading


def test_extract_plain_text_document() -> None:
    extracted = extract_document(
        b"This is a plain text offer letter with enough content to read.",
        filename="offer.txt",
        media_type="text/plain",
    )

    assert extracted.extension == ".txt"
    assert extracted.extraction_quality == ExtractionQuality.GOOD.value
    assert extracted.segments[0].page_number is None
    assert "plain text offer" in extracted.segments[0].text


def test_extract_markdown_document_keeps_first_heading() -> None:
    extracted = extract_document(
        b"# Offer Terms\n\nBase salary is listed here with bonus language.",
        filename="offer.md",
        media_type="text/markdown",
    )

    assert extracted.extension == ".md"
    assert extracted.segments[0].section_heading == "Offer Terms"
    assert first_markdown_heading(extracted.segments[0].text) == "Offer Terms"


def test_extract_pdf_document_uses_langchain_page_loader(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakePyPDFLoader:
        def __init__(self, path: str, mode: str) -> None:
            calls.append({"path": path, "mode": mode})

        def load(self) -> list[SimpleNamespace]:
            return [
                SimpleNamespace(
                    page_content="This page has enough readable offer terms.",
                    metadata={"page": 0},
                )
            ]

    monkeypatch.setattr(langchain_community.document_loaders, "PyPDFLoader", FakePyPDFLoader)

    extracted = extract_document(
        b"%PDF bytes",
        filename="offer.pdf",
        media_type="application/pdf",
    )

    assert calls[0]["mode"] == "page"
    assert extracted.extension == ".pdf"
    assert extracted.segments[0].page_number == 1
    assert "readable offer terms" in extracted.segments[0].text
