"""Input guardrails for extracted document text."""

from dataclasses import dataclass

from app.rag.extraction import ExtractedDocument, ExtractionQuality

PROMPT_INJECTION_PATTERNS = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "disregard previous instructions",
    "disregard all prior instructions",
    "system prompt",
    "developer message",
    "reveal your instructions",
    "jailbreak",
    "do not obey",
    "override your instructions",
)


@dataclass(frozen=True)
class GuardrailFinding:
    """A guardrail signal detected in an extracted document."""

    code: str
    message: str
    page_number: int | None = None


@dataclass(frozen=True)
class GuardrailResult:
    """Guardrail findings and derived document-level status."""

    findings: tuple[GuardrailFinding, ...]

    @property
    def is_suspicious(self) -> bool:
        """Return whether any prompt-injection-like text was detected."""
        return any(finding.code == "prompt_injection_signal" for finding in self.findings)


def check_extracted_document(
    extracted_document: ExtractedDocument,
    *,
    extension: str,
    size_bytes: int,
    max_size_bytes: int,
    allowed_extensions: frozenset[str],
) -> GuardrailResult:
    """Check extracted content without deleting or rewriting suspicious text."""
    findings: list[GuardrailFinding] = []

    if extension not in allowed_extensions:
        findings.append(
            GuardrailFinding(
                code="unsupported_file_type",
                message="file extension is not allowed for extraction",
            )
        )

    if size_bytes > max_size_bytes:
        findings.append(
            GuardrailFinding(
                code="file_too_large",
                message="file exceeds configured upload size limit",
            )
        )

    if extracted_document.extraction_quality == ExtractionQuality.POOR.value:
        findings.append(
            GuardrailFinding(
                code="poor_extraction_quality",
                message="document-level extraction produced little readable text",
            )
        )

    for segment in extracted_document.segments:
        if segment.extraction_quality == ExtractionQuality.POOR.value:
            findings.append(
                GuardrailFinding(
                    code="poor_segment_extraction_quality",
                    message="segment extraction produced little readable text",
                    page_number=segment.page_number,
                )
            )

        lowered = segment.text.lower()
        if any(pattern in lowered for pattern in PROMPT_INJECTION_PATTERNS):
            findings.append(
                GuardrailFinding(
                    code="prompt_injection_signal",
                    message="segment contains prompt-injection-like instructions",
                    page_number=segment.page_number,
                )
            )

    return GuardrailResult(findings=tuple(findings))


def flags_for_text(text: str) -> tuple[str, ...]:
    """Return guardrail flags that apply directly to a chunk of text."""
    lowered = text.lower()
    flags = [
        "prompt_injection_signal" for pattern in PROMPT_INJECTION_PATTERNS if pattern in lowered
    ]
    return tuple(dict.fromkeys(flags))
