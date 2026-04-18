#!/usr/bin/env python3
"""
resume_builder.py — Generate a clean, minimal PDF resume from a JSON file.

Usage:
    python resume_builder.py resume.json
    python resume_builder.py resume.json --output my_resume.pdf

Style tweaks:
    Edit the STYLE dictionary below to adjust fonts, sizes, spacing, and margins.
"""

import sys
import json
import argparse
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    Table, TableStyle, KeepTogether
)
from reportlab.lib import colors


# ─────────────────────────────────────────────────────────────────────────────
# STYLE CONFIGURATION — tweak anything here to change the look of the resume
# ─────────────────────────────────────────────────────────────────────────────
STYLE = {
    # Page margins (in inches)
    "margin_top":    0.65,
    "margin_bottom": 0.65,
    "margin_left":   0.75,
    "margin_right":  0.75,

    # Fonts (must be one of ReportLab's built-in fonts or a registered TTF)
    # Built-ins: Helvetica, Times-Roman, Courier  (and their Bold/Italic variants)
    "font_name":       "Times-Roman",
    "font_name_bold":  "Times-Bold",
    "font_name_italic": "Times-Italic",

    # Font sizes (pt)
    "size_name":        22,
    "size_title":       10,
    "size_contact":      9,
    "size_section":     10,
    "size_body":         9,
    "size_bullet":       9,

    # Vertical spacing (pt)
    "space_after_name":      2,
    "space_after_contact":   6,
    "space_after_section":   3,
    "space_after_entry":     5,
    "space_after_bullet":    1,
    "space_between_sections": 6,

    # Horizontal rule thickness (pt) and color
    "rule_thickness": 0.6,
    "rule_color":     colors.black,

    # Bullet character and indent (pt)
    "bullet_char":   "•",
    "bullet_indent": 12,
}
# ─────────────────────────────────────────────────────────────────────────────


def build_styles(s):
    """Return a dict of ParagraphStyles derived from the STYLE config."""
    base = dict(fontName=s["font_name"], textColor=colors.black, leading=s["size_body"] * 1.35)

    return {
        "name": ParagraphStyle("name",
            fontName=s["font_name_bold"],
            fontSize=s["size_name"],
            leading=s["size_name"] * 1.1,
            alignment=TA_CENTER,
            spaceAfter=s["space_after_name"]),

        "person_title": ParagraphStyle("person_title",
            fontName=s["font_name"],
            fontSize=s["size_title"],
            leading=s["size_title"] * 1.3,
            alignment=TA_CENTER,
            spaceAfter=s["space_after_name"]),

        "contact": ParagraphStyle("contact",
            fontName=s["font_name"],
            fontSize=s["size_contact"],
            leading=s["size_contact"] * 1.4,
            alignment=TA_CENTER,
            spaceAfter=s["space_after_contact"]),

        "section": ParagraphStyle("section",
            fontName=s["font_name_bold"],
            fontSize=s["size_section"],
            leading=s["size_section"] * 1.3,
            spaceAfter=s["space_after_section"],
            spaceBefore=0),

        "body": ParagraphStyle("body",
            **base,
            fontSize=s["size_body"],
            spaceAfter=2),

        "bold": ParagraphStyle("bold",
            fontName=s["font_name_bold"],
            fontSize=s["size_body"],
            leading=s["size_body"] * 1.35),

        "italic": ParagraphStyle("italic",
            fontName=s["font_name_italic"],
            fontSize=s["size_body"],
            leading=s["size_body"] * 1.35),

        "bullet": ParagraphStyle("bullet",
            **base,
            fontSize=s["size_bullet"],
            leftIndent=s["bullet_indent"],
            spaceAfter=s["space_after_bullet"]),

        "right": ParagraphStyle("right",
            fontName=s["font_name"],
            fontSize=s["size_body"],
            leading=s["size_body"] * 1.35,
            alignment=TA_RIGHT),

        "right_italic": ParagraphStyle("right_italic",
            fontName=s["font_name_italic"],
            fontSize=s["size_body"],
            leading=s["size_body"] * 1.35,
            alignment=TA_RIGHT),
    }


def rule(s):
    return HRFlowable(
        width="100%",
        thickness=s["rule_thickness"],
        color=s["rule_color"],
        spaceAfter=s["space_after_section"],
        spaceBefore=0,
    )


def section_header(title, st, s):
    return [
        Paragraph(title.upper(), st["section"]),
        rule(s),
    ]


def two_col(left_para, right_para, page_width):
    """A simple two-column row: left-aligned | right-aligned."""
    t = Table([[left_para, right_para]], colWidths=[page_width * 0.65, page_width * 0.35])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING",   (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
    ]))
    return t


def build_header(data, st, s):
    story = []
    story.append(Paragraph(data["name"], st["name"]))
    if data.get("title"):
        story.append(Paragraph(data["title"], st["person_title"]))

    c = data.get("contact", {})
    parts = []
    for key in ("email", "phone", "location", "linkedin", "github", "website"):
        if c.get(key):
            parts.append(c[key])
    if parts:
        story.append(Paragraph("  ·  ".join(parts), st["contact"]))
    return story


def build_summary(data, st, s):
    if not data.get("summary"):
        return []
    story = section_header("Summary", st, s)
    story.append(Paragraph(data["summary"], st["body"]))
    story.append(Spacer(1, s["space_between_sections"]))
    return story


def build_experience(data, st, s, page_width):
    if not data.get("experience"):
        return []
    story = section_header("Experience", st, s)
    for i, job in enumerate(data["experience"]):
        title_para = Paragraph(
            f'<b>{job["title"]}</b>  <font name="{s["font_name_italic"]}">{job["company"]}</font>',
            st["body"])
        date_loc = f'{job.get("start", "")} – {job.get("end", "")}'
        if job.get("location"):
            date_loc += f'  ·  {job["location"]}'
        date_para = Paragraph(date_loc, st["right_italic"])

        entry = [two_col(title_para, date_para, page_width)]
        for bullet in job.get("bullets", []):
            entry.append(Paragraph(f'{s["bullet_char"]}  {bullet}', st["bullet"]))

        space = Spacer(1, s["space_after_entry"]) if i < len(data["experience"]) - 1 else Spacer(1, 0)
        entry.append(space)
        story.append(KeepTogether(entry))

    story.append(Spacer(1, s["space_between_sections"]))
    return story


def build_education(data, st, s, page_width):
    if not data.get("education"):
        return []
    story = section_header("Education", st, s)
    for edu in data["education"]:
        degree_para = Paragraph(
            f'<b>{edu["degree"]}</b>  <font name="{s["font_name_italic"]}">{edu["institution"]}</font>',
            st["body"])
        date_loc = f'{edu.get("start", "")} – {edu.get("end", "")}'
        if edu.get("location"):
            date_loc += f'  ·  {edu["location"]}'
        date_para = Paragraph(date_loc, st["right_italic"])
        entry = [two_col(degree_para, date_para, page_width)]
        if edu.get("notes"):
            entry.append(Paragraph(edu["notes"], st["body"]))
        story.append(KeepTogether(entry))
    story.append(Spacer(1, s["space_between_sections"]))
    return story


def build_skills(data, st, s):
    if not data.get("skills"):
        return []
    story = section_header("Skills", st, s)
    skills = data["skills"]
    if isinstance(skills, dict):
        for category, items in skills.items():
            line = f'<b>{category}:</b>  {", ".join(items)}'
            story.append(Paragraph(line, st["body"]))
    elif isinstance(skills, list):
        story.append(Paragraph(", ".join(skills), st["body"]))
    story.append(Spacer(1, s["space_between_sections"]))
    return story


def build_projects(data, st, s):
    if not data.get("projects"):
        return []
    story = section_header("Projects", st, s)
    for proj in data["projects"]:
        name_url = f'<b>{proj["name"]}</b>'
        if proj.get("url"):
            name_url += f'  —  {proj["url"]}'
        story.append(Paragraph(name_url, st["body"]))
        if proj.get("description"):
            story.append(Paragraph(proj["description"], st["body"]))
        story.append(Spacer(1, s["space_after_entry"]))
    story.append(Spacer(1, s["space_between_sections"]))
    return story


def build_certifications(data, st, s):
    if not data.get("certifications"):
        return []
    story = section_header("Certifications", st, s)
    for cert in data["certifications"]:
        story.append(Paragraph(f'{s["bullet_char"]}  {cert}', st["bullet"]))
    story.append(Spacer(1, s["space_between_sections"]))
    return story


def generate_resume(json_path: str, output_path: str):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    s = STYLE
    st = build_styles(s)

    page_w, page_h = letter
    usable_w = page_w - (s["margin_left"] + s["margin_right"]) * inch

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        topMargin=s["margin_top"] * inch,
        bottomMargin=s["margin_bottom"] * inch,
        leftMargin=s["margin_left"] * inch,
        rightMargin=s["margin_right"] * inch,
        title=data.get("name", "Resume"),
        author=data.get("name", ""),
    )

    story = []
    story += build_header(data, st, s)
    story.append(rule(s))

    story += build_summary(data, st, s)
    story += build_experience(data, st, s, usable_w)
    story += build_education(data, st, s, usable_w)
    story += build_skills(data, st, s)
    story += build_projects(data, st, s)
    story += build_certifications(data, st, s)

    doc.build(story)
    print(f"✓ Resume saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate a PDF resume from a JSON file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    parser.add_argument("json_file", help="Path to the resume JSON file")
    parser.add_argument("--output", "-o", default=None,
                        help="Output PDF path (default: same name as JSON, .pdf extension)")
    args = parser.parse_args()

    json_path = Path(args.json_file)
    if not json_path.exists():
        print(f"Error: file not found: {json_path}", file=sys.stderr)
        sys.exit(1)

    output_path = args.output or str(json_path.with_suffix(".pdf"))
    generate_resume(str(json_path), output_path)


if __name__ == "__main__":
    main()
