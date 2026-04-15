#!/usr/bin/env python3
"""
Resume Builder Web App — Flask backend
Runs on http://localhost:8030
"""

import json
import os
import sys
import traceback
from pathlib import Path
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory

# ── PDF generation (adapted from resume_builder.py) ──────────────────────────
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    Table, TableStyle, KeepTogether
)
from reportlab.lib import colors

# ─────────────────────────────────────────────────────────────────────────────
# Persistence — everything lives in one JSON file next to this script
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "data.json"

DEFAULT_DATA = {
    "templates": [
        {
            "id": "tpl_resume",
            "name": "Standard Resume",
            "description": "One-page resume with experience, education, and skills",
            "page_size": "letter",
            "sections": ["summary", "experience", "education", "skills", "projects", "certifications"],
            "style": {
                "font_name": "Times-Roman",
                "font_name_bold": "Times-Bold",
                "font_name_italic": "Times-Italic",
                "size_name": 22,
                "size_title": 10,
                "size_contact": 9,
                "size_section": 10,
                "size_body": 9,
                "size_bullet": 9,
                "margin_top": 0.65,
                "margin_bottom": 0.65,
                "margin_left": 0.75,
                "margin_right": 0.75,
                "space_after_name": 2,
                "space_after_contact": 6,
                "space_after_section": 3,
                "space_after_entry": 5,
                "space_after_bullet": 1,
                "space_between_sections": 6,
                "rule_thickness": 0.6,
                "bullet_char": "•",
                "bullet_indent": 12
            }
        },
        {
            "id": "tpl_cv",
            "name": "Academic CV",
            "description": "Expanded CV with publications focus; A4 page size",
            "page_size": "A4",
            "sections": ["summary", "education", "experience", "skills", "projects", "certifications"],
            "style": {
                "font_name": "Helvetica",
                "font_name_bold": "Helvetica-Bold",
                "font_name_italic": "Helvetica-Oblique",
                "size_name": 20,
                "size_title": 11,
                "size_contact": 9,
                "size_section": 10,
                "size_body": 9,
                "size_bullet": 9,
                "margin_top": 1.0,
                "margin_bottom": 1.0,
                "margin_left": 1.0,
                "margin_right": 1.0,
                "space_after_name": 3,
                "space_after_contact": 8,
                "space_after_section": 4,
                "space_after_entry": 6,
                "space_after_bullet": 1,
                "space_between_sections": 8,
                "rule_thickness": 0.4,
                "bullet_char": "–",
                "bullet_indent": 14
            }
        }
    ],
    "jobs": []
}

AVAILABLE_SECTIONS = ["summary", "experience", "education", "skills", "projects", "certifications"]
AVAILABLE_FONTS = {
    "Times-Roman": {"bold": "Times-Bold", "italic": "Times-Italic"},
    "Helvetica": {"bold": "Helvetica-Bold", "italic": "Helvetica-Oblique"},
    "Courier": {"bold": "Courier-Bold", "italic": "Courier-Oblique"},
}


def load_data():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(json.dumps(DEFAULT_DATA))  # deep copy


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# PDF generation helpers
# ─────────────────────────────────────────────────────────────────────────────

def build_styles(s):
    base = dict(fontName=s["font_name"], textColor=colors.black,
                leading=s["size_body"] * 1.35)
    return {
        "name": ParagraphStyle("name",
            fontName=s["font_name_bold"], fontSize=s["size_name"],
            leading=s["size_name"] * 1.1, alignment=TA_CENTER,
            spaceAfter=s["space_after_name"]),
        "person_title": ParagraphStyle("person_title",
            fontName=s["font_name"], fontSize=s["size_title"],
            leading=s["size_title"] * 1.3, alignment=TA_CENTER,
            spaceAfter=s["space_after_name"]),
        "contact": ParagraphStyle("contact",
            fontName=s["font_name"], fontSize=s["size_contact"],
            leading=s["size_contact"] * 1.4, alignment=TA_CENTER,
            spaceAfter=s["space_after_contact"]),
        "section": ParagraphStyle("section",
            fontName=s["font_name_bold"], fontSize=s["size_section"],
            leading=s["size_section"] * 1.3,
            spaceAfter=s["space_after_section"], spaceBefore=0),
        "body": ParagraphStyle("body", **base, fontSize=s["size_body"], spaceAfter=2),
        "bold": ParagraphStyle("bold", fontName=s["font_name_bold"],
            fontSize=s["size_body"], leading=s["size_body"] * 1.35),
        "italic": ParagraphStyle("italic", fontName=s["font_name_italic"],
            fontSize=s["size_body"], leading=s["size_body"] * 1.35),
        "bullet": ParagraphStyle("bullet", **base, fontSize=s["size_bullet"],
            leftIndent=s["bullet_indent"], spaceAfter=s["space_after_bullet"]),
        "right": ParagraphStyle("right", fontName=s["font_name"],
            fontSize=s["size_body"], leading=s["size_body"] * 1.35, alignment=TA_RIGHT),
        "right_italic": ParagraphStyle("right_italic", fontName=s["font_name_italic"],
            fontSize=s["size_body"], leading=s["size_body"] * 1.35, alignment=TA_RIGHT),
    }


def rule(s):
    return HRFlowable(width="100%", thickness=s["rule_thickness"],
                      color=colors.black, spaceAfter=s["space_after_section"], spaceBefore=0)


def section_header(title, st, s):
    return [Paragraph(title.upper(), st["section"]), rule(s)]


def two_col(left_para, right_para, page_width):
    t = Table([[left_para, right_para]], colWidths=[page_width * 0.65, page_width * 0.35])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def build_section(section_name, data, st, s, page_width):
    if section_name == "summary":
        if not data.get("summary"): return []
        story = section_header("Summary", st, s)
        story.append(Paragraph(data["summary"], st["body"]))
        story.append(Spacer(1, s["space_between_sections"]))
        return story

    elif section_name == "experience":
        if not data.get("experience"): return []
        story = section_header("Experience", st, s)
        for i, job in enumerate(data["experience"]):
            title_para = Paragraph(
                f'<b>{job["title"]}</b>  <font name="{s["font_name_italic"]}">{job["company"]}</font>',
                st["body"])
            date_loc = f'{job.get("start", "")} – {job.get("end", "")}'
            if job.get("location"): date_loc += f'  ·  {job["location"]}'
            entry = [two_col(title_para, Paragraph(date_loc, st["right_italic"]), page_width)]
            for bullet in job.get("bullets", []):
                entry.append(Paragraph(f'{s["bullet_char"]}  {bullet}', st["bullet"]))
            sp = Spacer(1, s["space_after_entry"]) if i < len(data["experience"]) - 1 else Spacer(1, 0)
            entry.append(sp)
            story.append(KeepTogether(entry))
        story.append(Spacer(1, s["space_between_sections"]))
        return story

    elif section_name == "education":
        if not data.get("education"): return []
        story = section_header("Education", st, s)
        for edu in data["education"]:
            degree_para = Paragraph(
                f'<b>{edu["degree"]}</b>  <font name="{s["font_name_italic"]}">{edu["institution"]}</font>',
                st["body"])
            date_loc = f'{edu.get("start", "")} – {edu.get("end", "")}'
            if edu.get("location"): date_loc += f'  ·  {edu["location"]}'
            entry = [two_col(degree_para, Paragraph(date_loc, st["right_italic"]), page_width)]
            if edu.get("notes"): entry.append(Paragraph(edu["notes"], st["body"]))
            story.append(KeepTogether(entry))
        story.append(Spacer(1, s["space_between_sections"]))
        return story

    elif section_name == "skills":
        if not data.get("skills"): return []
        story = section_header("Skills", st, s)
        skills = data["skills"]
        if isinstance(skills, dict):
            for cat, items in skills.items():
                story.append(Paragraph(f'<b>{cat}:</b>  {", ".join(items)}', st["body"]))
        elif isinstance(skills, list):
            story.append(Paragraph(", ".join(skills), st["body"]))
        story.append(Spacer(1, s["space_between_sections"]))
        return story

    elif section_name == "projects":
        if not data.get("projects"): return []
        story = section_header("Projects", st, s)
        for proj in data["projects"]:
            name_url = f'<b>{proj["name"]}</b>'
            if proj.get("url"): name_url += f'  —  {proj["url"]}'
            story.append(Paragraph(name_url, st["body"]))
            if proj.get("description"): story.append(Paragraph(proj["description"], st["body"]))
            story.append(Spacer(1, s["space_after_entry"]))
        story.append(Spacer(1, s["space_between_sections"]))
        return story

    elif section_name == "certifications":
        if not data.get("certifications"): return []
        story = section_header("Certifications", st, s)
        for cert in data["certifications"]:
            story.append(Paragraph(f'{s["bullet_char"]}  {cert}', st["bullet"]))
        story.append(Spacer(1, s["space_between_sections"]))
        return story

    return []


def generate_pdf(json_data: dict, template: dict, output_path: str):
    s = template["style"]
    st = build_styles(s)
    page_size = A4 if template.get("page_size", "letter").lower() == "a4" else letter
    page_w, _ = page_size
    usable_w = page_w - (s["margin_left"] + s["margin_right"]) * inch

    doc = SimpleDocTemplate(
        output_path,
        pagesize=page_size,
        topMargin=s["margin_top"] * inch,
        bottomMargin=s["margin_bottom"] * inch,
        leftMargin=s["margin_left"] * inch,
        rightMargin=s["margin_right"] * inch,
        title=json_data.get("name", "Resume"),
        author=json_data.get("name", ""),
    )

    # Header
    story = []
    story.append(Paragraph(json_data["name"], st["name"]))
    if json_data.get("title"):
        story.append(Paragraph(json_data["title"], st["person_title"]))
    c = json_data.get("contact", {})
    parts = [c[k] for k in ("email", "phone", "location", "linkedin", "github", "website") if c.get(k)]
    if parts:
        story.append(Paragraph("  ·  ".join(parts), st["contact"]))
    story.append(rule(s))

    # Sections in template order
    for section_name in template.get("sections", AVAILABLE_SECTIONS):
        story += build_section(section_name, json_data, st, s, usable_w)

    doc.build(story)


# ─────────────────────────────────────────────────────────────────────────────
# Flask app
# ─────────────────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder="static")


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ── Templates ─────────────────────────────────────────────────────────────────

@app.route("/api/templates", methods=["GET"])
def list_templates():
    data = load_data()
    return jsonify(data["templates"])


@app.route("/api/templates", methods=["POST"])
def create_template():
    data = load_data()
    body = request.json
    import uuid
    body["id"] = "tpl_" + uuid.uuid4().hex[:8]
    data["templates"].append(body)
    save_data(data)
    return jsonify(body), 201


@app.route("/api/templates/<tpl_id>", methods=["PUT"])
def update_template(tpl_id):
    data = load_data()
    for i, t in enumerate(data["templates"]):
        if t["id"] == tpl_id:
            body = request.json
            body["id"] = tpl_id
            data["templates"][i] = body
            save_data(data)
            return jsonify(body)
    return jsonify({"error": "Not found"}), 404


@app.route("/api/templates/<tpl_id>", methods=["DELETE"])
def delete_template(tpl_id):
    data = load_data()
    data["templates"] = [t for t in data["templates"] if t["id"] != tpl_id]
    save_data(data)
    return jsonify({"ok": True})


# ── Jobs ──────────────────────────────────────────────────────────────────────

@app.route("/api/jobs", methods=["GET"])
def list_jobs():
    data = load_data()
    return jsonify(data["jobs"])


@app.route("/api/jobs", methods=["POST"])
def create_job():
    data = load_data()
    body = request.json
    import uuid
    body["id"] = "job_" + uuid.uuid4().hex[:8]
    body.setdefault("created_at", datetime.now().isoformat())
    data["jobs"].append(body)
    save_data(data)
    return jsonify(body), 201


@app.route("/api/jobs/<job_id>", methods=["PUT"])
def update_job(job_id):
    data = load_data()
    for i, j in enumerate(data["jobs"]):
        if j["id"] == job_id:
            body = request.json
            body["id"] = job_id
            body.setdefault("created_at", j.get("created_at"))
            data["jobs"][i] = body
            save_data(data)
            return jsonify(body)
    return jsonify({"error": "Not found"}), 404


@app.route("/api/jobs/<job_id>", methods=["DELETE"])
def delete_job(job_id):
    data = load_data()
    data["jobs"] = [j for j in data["jobs"] if j["id"] != job_id]
    save_data(data)
    return jsonify({"ok": True})


# ── Generate ──────────────────────────────────────────────────────────────────

@app.route("/api/generate", methods=["POST"])
def generate():
    body = request.json
    # body: { job_ids: [...], template_id: str, output_dir: str }
    data = load_data()

    template = next((t for t in data["templates"] if t["id"] == body["template_id"]), None)
    if not template:
        return jsonify({"error": "Template not found"}), 404

    output_dir = Path(body.get("output_dir", str(Path.home() / "Documents")))
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return jsonify({"error": f"Cannot create output dir: {e}"}), 400

    results = []
    for job_id in body.get("job_ids", []):
        job = next((j for j in data["jobs"] if j["id"] == job_id), None)
        if not job:
            results.append({"job_id": job_id, "error": "Job not found"})
            continue

        json_path = job.get("json_path", "")
        if not json_path:
            results.append({"job_id": job_id, "error": "No JSON path set"})
            continue

        json_file = Path(json_path)
        if not json_file.exists():
            results.append({"job_id": job_id, "error": f"File not found: {json_path}"})
            continue

        try:
            with open(json_file, "r", encoding="utf-8") as f:
                resume_data = json.load(f)
        except Exception as e:
            results.append({"job_id": job_id, "error": f"JSON parse error: {e}"})
            continue

        # Determine output filename
        custom_name = job.get("output_name", "").strip()
        if custom_name:
            fname = custom_name if custom_name.endswith(".pdf") else custom_name + ".pdf"
        else:
            fname = json_file.stem + ".pdf"

        out_path = output_dir / fname

        try:
            generate_pdf(resume_data, template, str(out_path))
            results.append({"job_id": job_id, "output": str(out_path), "ok": True})
        except Exception as e:
            results.append({"job_id": job_id, "error": traceback.format_exc()})

    return jsonify({"results": results})


@app.route("/api/meta", methods=["GET"])
def meta():
    return jsonify({
        "available_sections": AVAILABLE_SECTIONS,
        "available_fonts": list(AVAILABLE_FONTS.keys()),
        "font_variants": AVAILABLE_FONTS,
    })


if __name__ == "__main__":
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    # Seed data file if missing
    if not DATA_FILE.exists():
        save_data(DEFAULT_DATA)
    app.run(host="0.0.0.0", port=8030, debug=False)
