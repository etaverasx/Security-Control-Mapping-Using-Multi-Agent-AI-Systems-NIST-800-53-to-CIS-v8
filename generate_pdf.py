# generate_pdf.py
# Called automatically by test_pipeline.py and run_batch.py after each pipeline run.
# Takes a result dict and output path, generates a clean PDF report.
# Never run this directly -- import generate_report() from your pipeline scripts.

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    Table, TableStyle, PageBreak
)
from datetime import datetime
import os


def build_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontSize=20,
            textColor=colors.HexColor("#1a1a2e"), spaceAfter=6),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontSize=11,
            textColor=colors.HexColor("#4a4a6a"), spaceAfter=16),
        "section": ParagraphStyle("section", parent=base["Heading1"], fontSize=13,
            textColor=colors.HexColor("#1a1a2e"), spaceBefore=18, spaceAfter=6),
        "body": ParagraphStyle("body", parent=base["Normal"], fontSize=9,
            leading=14, textColor=colors.HexColor("#2c2c2c"), spaceAfter=6),
        "label": ParagraphStyle("label", parent=base["Normal"], fontSize=8,
            textColor=colors.HexColor("#666666"), spaceAfter=2),
    }


def strip_boilerplate(text):
    """Remove CrewAI system/user prompt headers that leak into agent output."""
    if not text:
        return text
    # find where the actual content starts -- after the last ### User: / Current Task: block
    markers = ["Provide your complete response:", "you MUST return the actual complete content"]
    for marker in markers:
        idx = text.rfind(marker)
        if idx != -1:
            text = text[idx + len(marker):].strip()
            break
    return text


def clean_text(text):
    if not text:
        return ""
    text = text.replace("**", "").replace("*", "")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.strip()


def add_section_header(story, title, styles):
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a1a2e")))
    story.append(Paragraph(title, styles["section"]))


def add_search_results_table(story, verified_mappings, styles):
    rows = [["#", "CIS ID", "Title", "Function", "IG", "Similarity"]]
    for line in verified_mappings.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if line[0].isdigit() and "." in line[:3]:
            parts = line.split(". ", 1)
            num = parts[0]
            rest = parts[1] if len(parts) > 1 else ""
            cis_id = rest.split(":")[0].strip()
            title = rest.split(":", 1)[1].strip() if ":" in rest else rest
            rows.append([num, cis_id, title, "", "", ""])
        elif "Security Function:" in line and len(rows) > 1:
            sec, ig, sim = "", "", ""
            for part in line.split("|"):
                part = part.strip()
                if "Security Function:" in part:
                    sec = part.replace("Security Function:", "").strip()
                elif "IG:" in part:
                    ig = part.replace("IG:", "").strip()
                elif "Similarity:" in part:
                    sim = part.replace("Similarity:", "").strip()
            rows[-1][3] = sec
            rows[-1][4] = ig
            rows[-1][5] = sim

    col_widths = [0.25*inch, 0.65*inch, 3.2*inch, 0.8*inch, 0.45*inch, 0.65*inch]
    table = Table(rows, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f0f8")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    story.append(Spacer(1, 8))


def add_text_block(story, text, styles):
    if not text:
        return
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            story.append(Spacer(1, 4))
            continue
        cleaned = clean_text(para)
        if cleaned:
            story.append(Paragraph(cleaned, styles["body"]))


def generate_report(result, pdf_path):
    """
    Generate a PDF report from a pipeline result dict.
    result: the dict returned by run_mapping_pipeline()
    pdf_path: full path where the PDF should be saved
    """
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        leftMargin=0.85*inch,
        rightMargin=0.85*inch,
        topMargin=0.85*inch,
        bottomMargin=0.85*inch,
    )

    styles = build_styles()
    story = []

    # header
    story.append(Paragraph(
        f"{result.get('nist_id', '')}: {result.get('nist_title', '')}",
        styles["title"]
    ))
    story.append(Paragraph(
        f"Family: {result.get('nist_family', '')} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"NIST 800-53 Rev 5 &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"Pipeline time: {result.get('elapsed_seconds', 0)}s",
        styles["subtitle"]
    ))
    story.append(Paragraph(
        f"Generated: {datetime.now().strftime('%B %d, %Y %H:%M')} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"Capstone — Emmanuel Taveras, Fordham University",
        styles["label"]
    ))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a1a2e")))
    story.append(Spacer(1, 12))

    # section 1: nist analysis
    add_section_header(story, "1. NIST Control Analysis", styles)
    add_text_block(story, result.get("nist_analysis", ""), styles)

    # section 2: search results
    add_section_header(story, "2. Verified CIS Candidates (Semantic Search)", styles)
    story.append(Paragraph(
        "Retrieved via ChromaDB semantic search. "
        "Similarity scores are normalized cosine similarity (0.0-1.0).",
        styles["body"]
    ))
    story.append(Spacer(1, 6))
    add_search_results_table(story, result.get("verified_search_results", ""), styles)

    # section 3: classification
    add_section_header(story, "3. Mapping Classification (Agent 3)", styles)
    add_text_block(story, result.get("mapping_classification", ""), styles)

    # section 4: cis analysis
    story.append(PageBreak())
    add_section_header(story, "4. CIS Safeguard Analysis (Agent 2)", styles)
    add_text_block(story, result.get("cis_analysis", ""), styles)

    # section 5: interpretation
    story.append(PageBreak())
    add_section_header(story, "5. Mapping Interpretation & Coverage Summary (Agent 4)", styles)
    add_text_block(story, result.get("interpretation", ""), styles)

    doc.build(story)
    print(f"  PDF saved: {pdf_path}")
    return pdf_path