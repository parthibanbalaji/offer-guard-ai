# ruff: noqa: E501, I001
"""Generate realistic synthetic UAE offer-letter PDFs for local evals.

The generated PDFs are deliberately text-based, not scanned images, so the
Phase 3 extraction pipeline can exercise PDF text extraction without OCR.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path


DATASET_DIR = Path(__file__).parent / "sample_offers_v1"
PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN_X = 54


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


@dataclass(frozen=True)
class Offer:
    filename: str
    company: str
    brand: str
    address: list[str]
    reference: str
    date: str
    candidate: str
    candidate_address: list[str]
    role: str
    location: str
    start_date: str
    intro: str
    compensation: list[tuple[str, str]]
    clauses: list[tuple[str, str]]
    signer: str
    signer_title: str
    footer_note: str


class PdfCanvas:
    def __init__(self, title: str) -> None:
        self.title = title
        self.pages: list[list[str]] = []
        self.commands: list[str] = []
        self.y = PAGE_HEIGHT - 58
        self.page_number = 0
        self.new_page()

    def new_page(self) -> None:
        if self.commands:
            self._footer()
            self.pages.append(self.commands)
        self.page_number += 1
        self.commands = []
        self.y = PAGE_HEIGHT - 54
        self._header()

    def _header(self) -> None:
        self.set_color(0.06, 0.22, 0.34)
        self.rect(42, PAGE_HEIGHT - 58, 36, 24, fill=True)
        self.set_color(1, 1, 1)
        self.text(50, PAGE_HEIGHT - 51, self.title[:2].upper(), 12, "Helvetica-Bold")
        self.set_color(0.06, 0.22, 0.34)
        self.text(90, PAGE_HEIGHT - 45, self.title, 13, "Helvetica-Bold")
        self.set_color(0.35, 0.35, 0.35)
        self.text(90, PAGE_HEIGHT - 61, "Human Resources Department", 8)
        self.set_color(0.08, 0.38, 0.55)
        self.line(42, PAGE_HEIGHT - 75, PAGE_WIDTH - 42, PAGE_HEIGHT - 75, 1.2)
        self.y = PAGE_HEIGHT - 96

    def _footer(self) -> None:
        self.set_color(0.65, 0.65, 0.65)
        self.line(42, 42, PAGE_WIDTH - 42, 42, 0.4)
        self.text(
            42, 28, "Synthetic PDF fixture for OfferGuard evaluation - not a real offer letter", 7
        )
        self.text(PAGE_WIDTH - 92, 28, f"Page {self.page_number}", 7)

    def set_color(self, r: float, g: float, b: float) -> None:
        self.commands.append(f"{r:.3f} {g:.3f} {b:.3f} rg")
        self.commands.append(f"{r:.3f} {g:.3f} {b:.3f} RG")

    def text(self, x: float, y: float, value: str, size: int = 10, font: str = "Helvetica") -> None:
        self.commands.append(
            f"BT /{font} {size} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({_pdf_escape(value)}) Tj ET"
        )

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float = 0.6) -> None:
        self.commands.append(f"{width:.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def rect(self, x: float, y: float, width: float, height: float, fill: bool = False) -> None:
        op = "f" if fill else "S"
        self.commands.append(f"{x:.2f} {y:.2f} {width:.2f} {height:.2f} re {op}")

    def ensure_space(self, height: int) -> None:
        if self.y - height < 70:
            self.new_page()

    def paragraph(self, value: str, size: int = 9, width: int = 96, gap: int = 8) -> None:
        lines = textwrap.wrap(value, width=width)
        self.ensure_space(len(lines) * (size + 3) + gap)
        self.set_color(0.10, 0.10, 0.10)
        for line in lines:
            self.text(MARGIN_X, self.y, line, size)
            self.y -= size + 3
        self.y -= gap

    def small_lines(self, lines: list[str]) -> None:
        self.ensure_space(len(lines) * 11 + 8)
        self.set_color(0.20, 0.20, 0.20)
        for line in lines:
            self.text(MARGIN_X, self.y, line, 8)
            self.y -= 11
        self.y -= 8

    def heading(self, value: str) -> None:
        self.ensure_space(24)
        self.set_color(0.06, 0.22, 0.34)
        self.text(MARGIN_X, self.y, value, 10, "Helvetica-Bold")
        self.y -= 14
        self.set_color(0.80, 0.80, 0.80)
        self.line(MARGIN_X, self.y, PAGE_WIDTH - MARGIN_X, self.y, 0.4)
        self.y -= 12

    def key_value(self, label: str, value: str) -> None:
        self.ensure_space(16)
        self.set_color(0.12, 0.12, 0.12)
        self.text(MARGIN_X, self.y, label, 9, "Helvetica-Bold")
        self.text(MARGIN_X + 132, self.y, value, 9)
        self.y -= 14

    def compensation_table(self, rows: list[tuple[str, str]]) -> None:
        row_h = 18
        table_h = row_h * (len(rows) + 1)
        self.ensure_space(table_h + 14)
        x = MARGIN_X
        w1 = 280
        w2 = 160
        self.set_color(0.90, 0.94, 0.96)
        self.rect(x, self.y - row_h + 5, w1 + w2, row_h, fill=True)
        self.set_color(0.06, 0.22, 0.34)
        self.text(x + 8, self.y - 7, "Component", 9, "Helvetica-Bold")
        self.text(x + w1 + 8, self.y - 7, "Amount / Detail", 9, "Helvetica-Bold")
        self.y -= row_h
        self.set_color(0.60, 0.60, 0.60)
        for label, amount in rows:
            self.rect(x, self.y - row_h + 5, w1 + w2, row_h)
            self.line(x + w1, self.y + 5, x + w1, self.y - row_h + 5, 0.4)
            self.set_color(0.12, 0.12, 0.12)
            self.text(x + 8, self.y - 7, label, 8)
            self.text(x + w1 + 8, self.y - 7, amount, 8)
            self.y -= row_h
            self.set_color(0.60, 0.60, 0.60)
        self.y -= 14

    def finish(self) -> list[list[str]]:
        self._footer()
        self.pages.append(self.commands)
        return self.pages


def _build_pdf(title: str, pages: list[list[str]]) -> bytes:
    objects: list[bytes] = []

    def add_object(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog_id = add_object(b"<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = add_object(b"<< /Type /Pages /Kids [] /Count 0 >>")
    font_regular_id = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font_bold_id = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    page_ids: list[int] = []
    content_ids: list[int] = []

    for commands in pages:
        stream = "\n".join(commands).encode("latin-1", errors="replace")
        content_id = add_object(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
        content_ids.append(content_id)
        page_id = add_object(
            (
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                f"/Resources << /Font << /Helvetica {font_regular_id} 0 R /Helvetica-Bold {font_bold_id} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode()
        )
        page_ids.append(page_id)

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
    objects[catalog_id - 1] = b"<< /Type /Catalog /Pages 2 0 R >>"

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for idx, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{idx} 0 obj\n".encode())
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref_at = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info << /Title ({_pdf_escape(title)}) >> >>\n"
            f"startxref\n{xref_at}\n%%EOF\n"
        ).encode()
    )
    return bytes(output)


def render_offer(offer: Offer) -> bytes:
    canvas = PdfCanvas(offer.brand)
    canvas.small_lines(offer.address)
    canvas.key_value("Reference", offer.reference)
    canvas.key_value("Date", offer.date)
    canvas.small_lines([offer.candidate, *offer.candidate_address])
    canvas.set_color(0.06, 0.22, 0.34)
    canvas.text(
        MARGIN_X, canvas.y, f"Subject: Offer of Employment - {offer.role}", 11, "Helvetica-Bold"
    )
    canvas.y -= 22
    canvas.paragraph(f"Dear {offer.candidate.split()[0]},")
    canvas.paragraph(offer.intro)
    canvas.heading("Position Details")
    canvas.key_value("Employer", offer.company)
    canvas.key_value("Position", offer.role)
    canvas.key_value("Work location", offer.location)
    canvas.key_value("Expected start date", offer.start_date)
    canvas.heading("Monthly Remuneration")
    canvas.compensation_table(offer.compensation)
    for heading, text in offer.clauses:
        canvas.heading(heading)
        canvas.paragraph(text)
    canvas.heading("Acceptance")
    canvas.paragraph(
        "Please sign and return a copy of this offer letter by the acceptance date stated by HR. "
        "The final employment contract, work permit approval and completion of onboarding checks remain required."
    )
    canvas.y -= 4
    canvas.key_value("For the employer", offer.signer)
    canvas.key_value("Title", offer.signer_title)
    canvas.y -= 22
    canvas.line(MARGIN_X, canvas.y, MARGIN_X + 160, canvas.y, 0.5)
    canvas.line(MARGIN_X + 250, canvas.y, MARGIN_X + 430, canvas.y, 0.5)
    canvas.y -= 12
    canvas.text(MARGIN_X, canvas.y, "Authorized signature", 8)
    canvas.text(MARGIN_X + 250, canvas.y, "Candidate signature / date", 8)
    canvas.y -= 24
    canvas.paragraph(offer.footer_note, size=7, width=110)
    return _build_pdf(offer.brand, canvas.finish())


OFFERS = [
    Offer(
        filename="01_mainland_software_engineer_compliant.pdf",
        company="Desert Falcon Technologies LLC",
        brand="Desert Falcon",
        address=[
            "Office 1804, Bay Square Building 7, Business Bay, Dubai, UAE",
            "TRN 100487392100003 | hr@desertfalcon.example",
        ],
        reference="DFT/HR/OFFER/2026/091",
        date="17 August 2026",
        candidate="Mariam Khalid",
        candidate_address=["Al Nahda, Dubai, United Arab Emirates"],
        role="Software Engineer",
        location="Business Bay, Dubai, United Arab Emirates",
        start_date="1 September 2026",
        intro=(
            "We are pleased to offer you employment with Desert Falcon Technologies LLC. This letter "
            "summarises the principal commercial terms to be reflected in the UAE employment contract."
        ),
        compensation=[
            ("Basic salary", "AED 14,000 per month"),
            ("Housing allowance", "AED 5,000 per month"),
            ("Transport allowance", "AED 2,000 per month"),
            ("Other allowance", "AED 1,000 per month"),
            ("Gross monthly salary", "AED 22,000 paid through WPS"),
        ],
        clauses=[
            (
                "Contract and Probation",
                "Your employment will be a full-time limited-term UAE mainland contract. The probation period is three months. Either party may terminate during probation by giving notice in accordance with applicable UAE labour law.",
            ),
            (
                "Working Hours",
                "Normal working hours are eight hours per day, Monday to Friday. Approved overtime and Ramadan working-hour adjustments will be handled in accordance with UAE labour law and company policy.",
            ),
            (
                "Leave and Benefits",
                "You are entitled to annual leave, sick leave, public holidays, medical insurance and end-of-service gratuity in accordance with UAE labour law. Annual leave entitlement is 30 calendar days after completing one year of service.",
            ),
            (
                "Notice and Termination",
                "After probation, either party may terminate employment by giving 60 days written notice. The company may place you on garden leave or pay in lieu of notice where permitted.",
            ),
            (
                "Confidentiality",
                "You must protect company confidential information during and after employment. This obligation does not prevent lawful disclosures to regulators or competent authorities.",
            ),
            (
                "Governing Law",
                "This offer and the employment relationship are governed by applicable UAE law and the competent UAE labour authorities and courts.",
            ),
        ],
        signer="Noura Al Mansoori",
        signer_title="Head of People Operations",
        footer_note="This synthetic fixture is intentionally formatted like a normal HR PDF for extraction and retrieval testing.",
    ),
    Offer(
        filename="02_probation_notice_risk_operations_manager.pdf",
        company="Al Noor Logistics Services LLC",
        brand="Al Noor Logistics",
        address=[
            "Warehouse B12, Industrial Area 13, Sharjah, UAE",
            "PO Box 78162 | recruitment@alnoorlogistics.example",
        ],
        reference="ANL-HR-2668-26",
        date="24 August 2026",
        candidate="Rakesh Menon",
        candidate_address=["Al Majaz 2, Sharjah, UAE"],
        role="Operations Manager",
        location="Sharjah, United Arab Emirates and other company sites as required",
        start_date="15 September 2026",
        intro="Following your interviews, we are pleased to offer you the position below, subject to successful reference checks and visa processing.",
        compensation=[
            ("Total package", "AED 18,500 per month"),
            ("Salary split", "To be determined by company payroll"),
            ("Mobile allowance", "Included in total package"),
            ("Bonus", "Discretionary, not guaranteed"),
        ],
        clauses=[
            (
                "Probation",
                "Your probation period will be six months. The company may terminate the employment at any time during probation without notice or payment, and the employee must give 90 days notice if resigning during probation.",
            ),
            (
                "Working Hours",
                "You will work the hours necessary for logistics operations, including nights, weekends and public holidays when required. No separate overtime is payable unless approved by the Managing Director in advance.",
            ),
            (
                "Annual Leave",
                "Annual leave will be granted as per business requirements and company policy after management approval.",
            ),
            (
                "Termination After Probation",
                "After confirmation, the employee must give 90 days notice. The company may terminate by giving 30 days notice or salary in lieu, at its sole discretion.",
            ),
            (
                "Non-Competition",
                "For 24 months after leaving, you must not work for any logistics, transport, warehouse, shipping or supply-chain business in the UAE or GCC.",
            ),
            (
                "Governing Law",
                "This offer is subject to UAE law and company policies as amended from time to time.",
            ),
        ],
        signer="Faisal Rahman",
        signer_title="HR & Administration Manager",
        footer_note="Synthetic fixture with intentionally risky probation, notice and restrictive-covenant wording.",
    ),
    Offer(
        filename="03_unclear_compensation_sales_executive.pdf",
        company="Gulf Pearl Trading LLC",
        brand="Gulf Pearl Trading",
        address=[
            "12th Floor, Corniche Plaza, Abu Dhabi, UAE",
            "www.gulfpearl.example | careers@gulfpearl.example",
        ],
        reference="GPT/OFFER/SE/1184",
        date="2 September 2026",
        candidate="Anika Sharma",
        candidate_address=["Tourist Club Area, Abu Dhabi, UAE"],
        role="Sales Executive",
        location="Abu Dhabi, UAE",
        start_date="21 September 2026",
        intro="We are delighted to confirm our intention to employ you as Sales Executive for our FMCG distribution division.",
        compensation=[
            ("Monthly package", "AED 9,500 inclusive of all allowances"),
            ("Commission", "Target based, scheme may change monthly"),
            ("Basic salary", "Included in monthly package"),
            ("Medical insurance", "Company plan after visa issuance"),
        ],
        clauses=[
            (
                "Salary",
                "The monthly package is inclusive of basic salary, accommodation, transportation, telephone and all other allowances. Payroll will allocate the basic salary internally for administrative purposes.",
            ),
            (
                "Probation and Notice",
                "The probation period is six months. During probation, either party may end employment in line with UAE labour law. After confirmation, notice is 30 days.",
            ),
            (
                "Targets and Incentives",
                "Commission is payable only if the employee is actively employed on the payout date. The company may amend the commission plan without prior notice.",
            ),
            (
                "Leave",
                "Annual leave and sick leave will be as per UAE labour law and company policy.",
            ),
            (
                "Deductions",
                "The company may deduct unreturned stock, damaged samples, traffic fines, advances and other amounts owed from salary or final settlement where permitted by law.",
            ),
            (
                "End of Service",
                "End-of-service benefits will be calculated as required by UAE law.",
            ),
        ],
        signer="Hiba Qureshi",
        signer_title="Senior Recruitment Officer",
        footer_note="Synthetic fixture focused on unclear basic salary and allowance breakdown.",
    ),
    Offer(
        filename="04_leave_hours_customer_support_risk.pdf",
        company="Blue Palm Contact Centre LLC",
        brand="Blue Palm",
        address=["Office 502, Ajman One Tower, Ajman, UAE", "Tel +971 6 555 0199"],
        reference="BPCC/HR/CS/2026-44",
        date="5 September 2026",
        candidate="Sara Fernandes",
        candidate_address=["Al Rashidiya 3, Ajman, UAE"],
        role="Customer Support Representative",
        location="Ajman, UAE",
        start_date="28 September 2026",
        intro="This offer sets out the main terms for your proposed employment in our customer operations team.",
        compensation=[
            ("Basic salary", "AED 4,000 per month"),
            ("Allowances", "AED 2,000 per month"),
            ("Gross salary", "AED 6,000 per month"),
            ("Shift allowance", "Included unless separately approved"),
        ],
        clauses=[
            (
                "Shift Pattern",
                "You will work six days per week on rotating shifts. Shift timings may change at short notice depending on campaign requirements. The employee agrees to work additional hours without separate overtime unless approved in writing.",
            ),
            (
                "Annual Leave",
                "Paid annual leave is 21 calendar days per completed year of service. Leave during the first year is subject to operational approval and may be deferred.",
            ),
            (
                "Sick Leave",
                "Sick leave is unpaid during the first year of employment unless the company decides otherwise.",
            ),
            (
                "Probation",
                "Probation is six months. Termination during probation will follow applicable UAE labour law.",
            ),
            (
                "Policies",
                "You agree that the company may amend working hours, leave schedules, location and benefits based on client requirements.",
            ),
            ("Applicable Law", "UAE law applies."),
        ],
        signer="Omar Haddad",
        signer_title="HR Supervisor",
        footer_note="Synthetic fixture with practical call-centre wording and leave/hour risks.",
    ),
    Offer(
        filename="05_non_compete_confidentiality_sales_director.pdf",
        company="Atlas Medical Supplies LLC",
        brand="Atlas Medical",
        address=[
            "Unit 210, Dubai Healthcare City, Dubai, UAE",
            "Commercial Licence 782144 | hr@atlasmedical.example",
        ],
        reference="AMS-EXE-OFFER-2026-07",
        date="9 September 2026",
        candidate="Daniel Okafor",
        candidate_address=["Jumeirah Village Circle, Dubai, UAE"],
        role="Senior Sales Director",
        location="Dubai, UAE with regional travel",
        start_date="1 October 2026",
        intro="We are pleased to offer you a leadership role within our medical distribution business.",
        compensation=[
            ("Basic salary", "AED 25,000 per month"),
            ("Housing allowance", "AED 12,000 per month"),
            ("Transport allowance", "AED 5,000 per month"),
            ("Other allowance", "AED 3,000 per month"),
            ("Gross salary", "AED 45,000 per month"),
        ],
        clauses=[
            (
                "Probation and Notice",
                "The probation period is six months. After confirmation, either party may terminate by giving 90 days written notice.",
            ),
            (
                "Sales Incentive",
                "Participation in the sales incentive plan is discretionary. No incentive is earned unless the company has collected customer payment and the employee remains employed on the payout date.",
            ),
            (
                "Confidentiality",
                "All customer names, pricing, supplier terms, product margins, tender strategies and market information are company confidential. These restrictions apply indefinitely after termination.",
            ),
            (
                "Non-Competition",
                "For 24 months after termination, you must not work for, advise, invest in or assist any business selling healthcare, medical, laboratory, pharmaceutical or related products in the UAE, GCC, Middle East, Europe, Asia or any market where the company may operate.",
            ),
            (
                "Non-Solicitation",
                "For 24 months you must not contact any customer, hospital, clinic, distributor, employee or supplier that had any relationship with the company during your employment.",
            ),
            ("Governing Law", "This offer is governed by UAE law."),
        ],
        signer="Layla Saeed",
        signer_title="Chief Commercial Officer",
        footer_note="Synthetic fixture with broad post-termination restrictions for retrieval testing.",
    ),
    Offer(
        filename="06_free_zone_jurisdiction_ambiguity_finance_analyst.pdf",
        company="Crescent Bay Capital FZ-LLC",
        brand="Crescent Bay Capital",
        address=[
            "Level 15, Index Tower, Dubai International Financial Centre, Dubai, UAE",
            "Private and confidential",
        ],
        reference="CBC/HR/FA/2026/33",
        date="12 September 2026",
        candidate="Yusuf Khan",
        candidate_address=["Dubai Marina, Dubai, UAE"],
        role="Finance Analyst",
        location="Dubai International Financial Centre, Dubai, UAE",
        start_date="5 October 2026",
        intro="We are pleased to offer you employment in our finance team, subject to regulatory and background checks.",
        compensation=[
            ("Monthly salary", "AED 16,000"),
            ("Allowance breakdown", "To be issued later by payroll"),
            ("Bonus", "Discretionary annual bonus opportunity"),
            ("Benefits", "Medical insurance under company scheme"),
        ],
        clauses=[
            (
                "Employment Framework",
                "The company office is located in a UAE free zone. The final contract may be issued under mainland UAE labour law, DIFC employment law or another applicable free-zone framework depending on internal structuring.",
            ),
            (
                "Probation",
                "The probation period is six months. Notice during probation will be advised in the final contract.",
            ),
            (
                "Hours and Leave",
                "Working hours and annual leave will follow company policy applicable to the relevant employing entity.",
            ),
            (
                "Confidentiality and Data",
                "You must keep investor information, financial models, client data and fund information confidential during and after employment.",
            ),
            (
                "Jurisdiction",
                "The courts of Dubai shall have exclusive jurisdiction over disputes, except where mandatory UAE law, DIFC law or another free-zone authority applies.",
            ),
            (
                "Condition Precedent",
                "This offer is conditional on completion of compliance screening and approval by the relevant licensing authority where required.",
            ),
        ],
        signer="Maha Ibrahim",
        signer_title="People & Compliance Lead",
        footer_note="Synthetic fixture focused on free-zone and jurisdiction ambiguity.",
    ),
    Offer(
        filename="07_visa_relocation_repayment_marketing_specialist.pdf",
        company="Sunrise Hospitality Group LLC",
        brand="Sunrise Hospitality",
        address=[
            "Cluster T, Jumeirah Lakes Towers, Dubai, UAE",
            "PO Box 504229 | people@sunrisehospitality.example",
        ],
        reference="SHG/Offer/MKT/7721",
        date="16 September 2026",
        candidate="Elena Rossi",
        candidate_address=["Current address: Milan, Italy"],
        role="Marketing Specialist",
        location="Dubai, UAE",
        start_date="20 October 2026",
        intro="We are pleased to make this conditional offer for employment in Dubai, subject to visa issuance and completion of onboarding formalities.",
        compensation=[
            ("Basic salary", "AED 8,000 per month"),
            ("Allowances", "AED 5,000 per month"),
            ("Gross salary", "AED 13,000 per month"),
            ("Relocation support", "Flight and initial hotel arranged by company"),
        ],
        clauses=[
            (
                "Visa and Onboarding",
                "The company will arrange your UAE employment visa, work permit, Emirates ID process and medical insurance required for employment.",
            ),
            (
                "Repayment Undertaking",
                "If you resign or are terminated for cause within 18 months, you must repay all recruitment, visa, work permit, Emirates ID, medical test, flight, temporary accommodation and agency costs paid by the company.",
            ),
            (
                "Probation",
                "The probation period is six months. During probation, notice will be handled in accordance with UAE labour law.",
            ),
            (
                "Leave",
                "You are entitled to 30 calendar days of annual leave after one year of service. Sick leave is as per UAE labour law.",
            ),
            (
                "Notice",
                "After probation, either party may terminate by giving 45 days written notice.",
            ),
            ("Governing Law", "This employment is governed by UAE law."),
        ],
        signer="Khaled Barakat",
        signer_title="Director of Human Resources",
        footer_note="Synthetic fixture with visa and relocation repayment wording.",
    ),
    Offer(
        filename="08_brief_offer_missing_terms_consultant.pdf",
        company="Emirates Star Services LLC",
        brand="Emirates Star Services",
        address=["Mussafah, Abu Dhabi, UAE", "HR Department"],
        reference="ESS-2026-Offer-19",
        date="21 September 2026",
        candidate="Priya Nair",
        candidate_address=["Abu Dhabi, UAE"],
        role="Consultant",
        location="United Arab Emirates",
        start_date="To be confirmed",
        intro="We are pleased to offer you employment with Emirates Star Services LLC in the United Arab Emirates.",
        compensation=[
            ("Package", "AED 17,000 per month"),
            ("Other details", "As per company policy"),
        ],
        clauses=[
            (
                "Terms",
                "Your start date, work location, reporting manager, probation period, leave entitlement, working hours, benefits, visa process, notice period and other terms will be confirmed in the employment contract and company policies after joining.",
            ),
            (
                "Policies",
                "You agree to follow all current and future policies of the company. The company may amend your duties, location, reporting line, working hours, benefits and policies at its discretion.",
            ),
            ("Acceptance", "Please sign below to accept this offer."),
        ],
        signer="Human Resources",
        signer_title="For Emirates Star Services LLC",
        footer_note="Synthetic fixture intentionally missing many key employment terms.",
    ),
]


def main() -> None:
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    for path in DATASET_DIR.iterdir():
        if path.is_file():
            path.unlink()

    readme = """# Sample UAE Offer PDFs v1

These are synthetic, realistic UAE private-sector offer-letter PDFs for local testing and evals.
They are not real offers, legal advice, or templates for employment use.

The fixtures imitate common HR PDF patterns: letterhead, reference/date blocks, candidate details,
salary tables, signature blocks, page footers, and ordinary paragraph clauses. They are text-based
PDFs so the extraction pipeline can read them without OCR.

Coverage:

- compliant mainland offer
- probation and notice risks
- unclear salary/basic allowance split
- leave and working-hours risks
- non-compete and confidentiality risks
- free-zone/DIFC jurisdiction ambiguity
- visa and relocation repayment risks
- brief offer with missing mandatory terms

All names, companies, addresses, emails, references, and compensation figures are fictional.
"""
    (DATASET_DIR / "README.md").write_text(readme, encoding="utf-8")
    for offer in OFFERS:
        (DATASET_DIR / offer.filename).write_bytes(render_offer(offer))


if __name__ == "__main__":
    main()
