#!/usr/bin/env python3
"""Resume Builder Web App — Flask backend, runs on http://localhost:8030"""

import json, re, traceback, uuid
from pathlib import Path
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    Table, TableStyle, KeepTogether
)
from reportlab.lib import colors

BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "data.json"

# ─────────────────────────────────────────────────────────────────────────────
# Section type registry — the single source of truth for what types exist
# ─────────────────────────────────────────────────────────────────────────────
SECTION_TYPES = {
    "text": {
        "label": "Plain Text",
        "description": "A single block of prose. JSON key holds a string.",
        "json_shape": "string",
    },
    "entries": {
        "label": "Entries (header row + bullets)",
        "description": "List of entries with a title/org header row, optional date range & location, optional subtitle line, and bullet points. Use for Experience, Education, Awards, etc.",
        "json_shape": 'list of {title|degree|role, organization|company|institution, start?, end?, location?, subtitle?|notes?, bullets?: []}',
    },
    "skills": {
        "label": "Skills / Tags",
        "description": "A flat list or categorized dict. Renders comma-separated, one line per category.",
        "json_shape": "list<string>  OR  {category: list<string>}",
    },
    "bullets": {
        "label": "Bullet List",
        "description": "Simple bulleted list of strings.",
        "json_shape": "list<string>",
    },
    "url_list": {
        "label": "Items with URL + Bullets",
        "description": "List of named items, each with an optional URL, optional prose description, and optional bullet list. Use for Projects, Talks, etc.",
        "json_shape": 'list of {name, url?, description?, bullets?: []}',
    },
    "grouped_list": {
        "label": "Grouped Sub-sections",
        "description": "A list of sub-sections each with a bold heading and its own list of items. Each item has a title, optional details line, optional URL, and optional bullets. Use for Publications (Papers, Presentations…), Grants, etc.",
        "json_shape": 'list of {heading, items: [{title, details?, url?, bullets?: []}]}',
    },
}

AVAILABLE_FONTS = {
    "Times-Roman": {"bold": "Times-Bold",      "italic": "Times-Italic"},
    "Helvetica":   {"bold": "Helvetica-Bold",  "italic": "Helvetica-Oblique"},
    "Courier":     {"bold": "Courier-Bold",    "italic": "Courier-Oblique"},
}

BUILTIN_SECTIONS = [
    {"id": "sec_summary",        "display_name": "Summary",        "json_key": "summary",        "section_type": "text"},
    {"id": "sec_experience",     "display_name": "Experience",     "json_key": "experience",     "section_type": "entries"},
    {"id": "sec_education",      "display_name": "Education",      "json_key": "education",      "section_type": "entries"},
    {"id": "sec_skills",         "display_name": "Skills",         "json_key": "skills",         "section_type": "skills"},
    {"id": "sec_projects",       "display_name": "Projects",       "json_key": "projects",       "section_type": "url_list"},
    {"id": "sec_certifications", "display_name": "Certifications", "json_key": "certifications", "section_type": "bullets"},
    {"id": "sec_publications",   "display_name": "Publications",   "json_key": "publications",   "section_type": "grouped_list"},
]

DEFAULT_DATA = {
    "section_defs": BUILTIN_SECTIONS,
    "templates": [
        {
            "id": "tpl_resume",
            "name": "Standard Resume",
            "description": "One-page resume with experience, education, and skills",
            "page_size": "letter",
            "sections": ["sec_summary", "sec_experience", "sec_education",
                         "sec_skills", "sec_projects", "sec_certifications"],
            "style": {
                "font_name": "Times-Roman", "font_name_bold": "Times-Bold",
                "font_name_italic": "Times-Italic",
                "size_name": 22, "size_title": 10, "size_contact": 9,
                "size_section": 10, "size_body": 9, "size_bullet": 9,
                "margin_top": 0.65, "margin_bottom": 0.65,
                "margin_left": 0.75, "margin_right": 0.75,
                "space_after_name": 2, "space_after_contact": 6,
                "space_after_section": 3, "space_after_entry": 5,
                "space_after_bullet": 1, "space_between_sections": 6,
                "rule_thickness": 0.6, "bullet_char": "\u2022", "bullet_indent": 12,
            }
        },
        {
            "id": "tpl_cv",
            "name": "Academic CV",
            "description": "Expanded CV with publications; A4 page size",
            "page_size": "A4",
            "sections": ["sec_summary", "sec_education", "sec_experience",
                         "sec_skills", "sec_publications", "sec_projects", "sec_certifications"],
            "style": {
                "font_name": "Helvetica", "font_name_bold": "Helvetica-Bold",
                "font_name_italic": "Helvetica-Oblique",
                "size_name": 20, "size_title": 11, "size_contact": 9,
                "size_section": 10, "size_body": 9, "size_bullet": 9,
                "margin_top": 1.0, "margin_bottom": 1.0,
                "margin_left": 1.0, "margin_right": 1.0,
                "space_after_name": 3, "space_after_contact": 8,
                "space_after_section": 4, "space_after_entry": 6,
                "space_after_bullet": 1, "space_between_sections": 8,
                "rule_thickness": 0.4, "bullet_char": "\u2013", "bullet_indent": 14,
            }
        },
    ],
    "jobs": []
}


def load_data():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if "section_defs" not in d:
            d["section_defs"] = BUILTIN_SECTIONS
        return d
    return json.loads(json.dumps(DEFAULT_DATA))


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# Text helpers: escaping + hyperlink auto-detection
# ─────────────────────────────────────────────────────────────────────────────
_URL_RE = re.compile(
    r'(https?://[^\s<>"\')\]]+|www\.[a-zA-Z0-9](?:[^\s<>"\')\]]+))',
    re.IGNORECASE
)
LINK_COLOR = "#1a5fb4"


def linkify(text: str) -> str:
    """Replace bare URLs with ReportLab <link> tags."""
    if not text:
        return text
    def _repl(m):
        url = m.group(0)
        href = url if url.lower().startswith("http") else "https://" + url
        return f'<link href="{href}" color="{LINK_COLOR}">{url}</link>'
    return _URL_RE.sub(_repl, text)


def safe(value) -> str:
    """XML-escape a value then linkify URLs."""
    if value is None:
        return ""
    text = str(value)
    text = (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))
    return linkify(text)


# ─────────────────────────────────────────────────────────────────────────────
# PDF style builders
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
        "subheading": ParagraphStyle("subheading",
            fontName=s["font_name_bold"], fontSize=s["size_body"],
            leading=s["size_body"] * 1.4, spaceAfter=2, spaceBefore=4),
        "body": ParagraphStyle("body", **base, fontSize=s["size_body"], spaceAfter=2),
        "body_italic": ParagraphStyle("body_italic",
            fontName=s["font_name_italic"], fontSize=s["size_body"],
            leading=s["size_body"] * 1.35, textColor=colors.black, spaceAfter=2),
        "bullet": ParagraphStyle("bullet", **base, fontSize=s["size_bullet"],
            leftIndent=s["bullet_indent"], spaceAfter=s["space_after_bullet"]),
        "right_italic": ParagraphStyle("right_italic",
            fontName=s["font_name_italic"], fontSize=s["size_body"],
            leading=s["size_body"] * 1.35, alignment=TA_RIGHT),
    }


def rule(s):
    return HRFlowable(width="100%", thickness=s["rule_thickness"],
                      color=colors.black, spaceAfter=s["space_after_section"], spaceBefore=0)


def sec_header(display_name, st, s):
    return [Paragraph(display_name.upper(), st["section"]), rule(s)]


def anchor_header(display_name, st, s, first_block):
    """Return a KeepTogether of the section header + first_block (list of flowables)."""
    return KeepTogether(sec_header(display_name, st, s) + first_block)


def two_col(left, right, page_width):
    t = Table([[left, right]], colWidths=[page_width * 0.65, page_width * 0.35])
    t.setStyle(TableStyle([
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
        ("TOPPADDING",    (0,0),(-1,-1), 0),
        ("BOTTOMPADDING", (0,0),(-1,-1), 0),
    ]))
    return t


# ─────────────────────────────────────────────────────────────────────────────
# Section renderers
# ─────────────────────────────────────────────────────────────────────────────

def render_text(sec_def, data, st, s, pw):
    value = data.get(sec_def["json_key"])
    if not value:
        return []
    para = Paragraph(safe(value), st["body"])
    story = [anchor_header(sec_def["display_name"], st, s, [para])]
    story.append(Spacer(1, s["space_between_sections"]))
    return story


def render_entries(sec_def, data, st, s, pw):
    """
    Supports old field names (title/company/degree/institution) and new generic
    (title/organization). Adds subtitle/notes line and bullet list.
    """
    items = data.get(sec_def["json_key"])
    if not items:
        return []
    story = []
    for i, entry in enumerate(items):
        title = (entry.get("title") or entry.get("degree") or
                 entry.get("role") or "")
        org   = (entry.get("organization") or entry.get("company") or
                 entry.get("institution") or "")
        start    = entry.get("start", "")
        end      = entry.get("end", "")
        location = entry.get("location", "")

        left_html = f'<b>{safe(title)}</b>'
        if org:
            left_html += f'  <font name="{s["font_name_italic"]}">{safe(org)}</font>'

        date_loc = ""
        if start or end:
            date_loc = f'{safe(start)} \u2013 {safe(end)}'
        if location:
            date_loc += (f'  \u00b7  {safe(location)}' if date_loc else safe(location))

        block = [two_col(
            Paragraph(left_html, st["body"]),
            Paragraph(date_loc, st["right_italic"]),
            pw
        )]

        subtitle = entry.get("subtitle") or entry.get("notes")
        if subtitle:
            block.append(Paragraph(safe(subtitle), st["body_italic"]))

        for b in entry.get("bullets", []):
            block.append(Paragraph(
                f'{s["bullet_char"]}  {safe(b)}', st["bullet"]))

        block.append(Spacer(1, s["space_after_entry"] if i < len(items)-1 else 0))

        if i == 0:
            story.append(anchor_header(sec_def["display_name"], st, s, block))
        else:
            story.append(KeepTogether(block))

    story.append(Spacer(1, s["space_between_sections"]))
    return story


def render_skills(sec_def, data, st, s, pw):
    value = data.get(sec_def["json_key"])
    if not value:
        return []
    if isinstance(value, dict):
        paras = [Paragraph(
            f'<b>{safe(cat)}:</b>  {", ".join(safe(x) for x in items)}',
            st["body"]) for cat, items in value.items()]
    elif isinstance(value, list):
        paras = [Paragraph(", ".join(safe(x) for x in value), st["body"])]
    else:
        paras = []
    if not paras:
        return []
    story = [anchor_header(sec_def["display_name"], st, s, [paras[0]])]
    for p in paras[1:]:
        story.append(p)
    story.append(Spacer(1, s["space_between_sections"]))
    return story


def render_bullets(sec_def, data, st, s, pw):
    items = data.get(sec_def["json_key"])
    if not items:
        return []
    paras = [Paragraph(f'{s["bullet_char"]}  {safe(item)}', st["bullet"])
             for item in items]
    story = [anchor_header(sec_def["display_name"], st, s, [paras[0]])]
    for p in paras[1:]:
        story.append(p)
    story.append(Spacer(1, s["space_between_sections"]))
    return story


def render_url_list(sec_def, data, st, s, pw):
    """
    Items: {name, url?, description?, bullets?:[]}
    URL is auto-linkified. bullets is now a real bullet list.
    """
    items = data.get(sec_def["json_key"])
    if not items:
        return []
    story = []
    for i, item in enumerate(items):
        name = safe(item.get("name", ""))
        url  = item.get("url", "")
        if url:
            href = url if url.lower().startswith("http") else "https://" + url
            name_html = f'<b><link href="{href}" color="{LINK_COLOR}">{name}</link></b>'
        else:
            name_html = f'<b>{name}</b>'

        block = [Paragraph(name_html, st["body"])]

        desc = item.get("description", "")
        if desc:
            block.append(Paragraph(safe(desc), st["body"]))

        for b in item.get("bullets", []):
            block.append(Paragraph(
                f'{s["bullet_char"]}  {safe(b)}', st["bullet"]))

        block.append(Spacer(1, s["space_after_entry"] if i < len(items)-1 else 0))

        if i == 0:
            story.append(anchor_header(sec_def["display_name"], st, s, block))
        else:
            story.append(KeepTogether(block))

    story.append(Spacer(1, s["space_between_sections"]))
    return story


def render_grouped_list(sec_def, data, st, s, pw):
    """
    Groups: [{heading, items:[{title, details?, url?, bullets?:[]}]}]
    Designed for Publications: Papers, Presentations, etc.
    """
    groups = data.get(sec_def["json_key"])
    if not groups:
        return []
    story = []
    first_section_item = True  # tracks whether we've emitted the anchored header yet

    for g_idx, group in enumerate(groups):
        if not isinstance(group, dict):
            continue
        heading = group.get("heading", "")
        group_items = group.get("items", [])

        for i, item in enumerate(group_items):
            title   = safe(item.get("title", ""))
            details = item.get("details", "")
            url     = item.get("url", "")

            title_html = title if title else ""
            if url:
                href = url if url.lower().startswith("http") else "https://" + url
                title_html += (f'  <link href="{href}" color="{LINK_COLOR}">'
                               f'[Link]</link>')

            block = []
            if title_html:
                block.append(Paragraph(title_html, st["body"]))
            if details:
                block.append(Paragraph(safe(details), st["body_italic"]))
            for b in item.get("bullets", []):
                block.append(Paragraph(
                    f'{s["bullet_char"]}  {safe(b)}', st["bullet"]))

            gap = s["space_after_bullet"] + 2
            block.append(Spacer(1, gap if i < len(group_items)-1 else 2))

            if first_section_item:
                # Wrap section header + optional group subheading + first item together
                anchor_block = []
                if heading:
                    anchor_block.append(Paragraph(safe(heading), st["subheading"]))
                anchor_block += block
                story.append(anchor_header(sec_def["display_name"], st, s, anchor_block))
                first_section_item = False
            elif i == 0 and heading:
                # First item of a subsequent group: keep subheading with it
                story.append(KeepTogether([Paragraph(safe(heading), st["subheading"])] + block))
            else:
                story.append(KeepTogether(block))

        if g_idx < len(groups) - 1:
            story.append(Spacer(1, s["space_after_entry"]))

    story.append(Spacer(1, s["space_between_sections"]))
    return story


RENDERERS = {
    "text":         render_text,
    "entries":      render_entries,
    "skills":       render_skills,
    "bullets":      render_bullets,
    "url_list":     render_url_list,
    "grouped_list": render_grouped_list,
}


# ─────────────────────────────────────────────────────────────────────────────
# PDF generation entry point
# ─────────────────────────────────────────────────────────────────────────────

def generate_pdf(json_data: dict, template: dict, section_defs: list, output_path: str):
    s  = template["style"]
    st = build_styles(s)

    page_size = A4 if template.get("page_size", "letter").lower() == "a4" else letter
    page_w, _ = page_size
    usable_w  = page_w - (s["margin_left"] + s["margin_right"]) * inch

    doc = SimpleDocTemplate(
        output_path, pagesize=page_size,
        topMargin=s["margin_top"] * inch, bottomMargin=s["margin_bottom"] * inch,
        leftMargin=s["margin_left"] * inch, rightMargin=s["margin_right"] * inch,
        title=json_data.get("name", "Resume"), author=json_data.get("name", ""),
    )

    sec_by_id = {sd["id"]: sd for sd in section_defs}

    story = []
    # Header block
    story.append(Paragraph(safe(json_data.get("name", "")), st["name"]))
    if json_data.get("title"):
        story.append(Paragraph(safe(json_data["title"]), st["person_title"]))

    c = json_data.get("contact", {})
    parts = []
    for key in ("email", "phone", "location", "linkedin", "github", "website"):
        if c.get(key):
            val = c[key]
            if re.match(r'https?://', val) or re.match(r'www\.', val, re.I):
                href = val if val.lower().startswith("http") else "https://" + val
                parts.append(f'<link href="{href}" color="{LINK_COLOR}">{safe(val)}</link>')
            else:
                parts.append(safe(val))
    if parts:
        story.append(Paragraph("  \u00b7  ".join(parts), st["contact"]))

    story.append(rule(s))

    for sec_id in template.get("sections", []):
        sec_def  = sec_by_id.get(sec_id)
        if not sec_def:
            continue
        renderer = RENDERERS.get(sec_def.get("section_type", "text"), render_text)
        story   += renderer(sec_def, json_data, st, s, usable_w)

    doc.build(story)


# ─────────────────────────────────────────────────────────────────────────────
# Flask application
# ─────────────────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder="static")


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# Section definitions ──────────────────────────────────────────────────────────

@app.route("/api/section_defs", methods=["GET"])
def list_section_defs():
    return jsonify(load_data()["section_defs"])

@app.route("/api/section_defs", methods=["POST"])
def create_section_def():
    data = load_data()
    body = request.json
    body["id"] = "sec_" + uuid.uuid4().hex[:8]
    data["section_defs"].append(body)
    save_data(data)
    return jsonify(body), 201

@app.route("/api/section_defs/<sec_id>", methods=["PUT"])
def update_section_def(sec_id):
    data = load_data()
    for i, sd in enumerate(data["section_defs"]):
        if sd["id"] == sec_id:
            body = request.json
            body["id"] = sec_id
            data["section_defs"][i] = body
            save_data(data)
            return jsonify(body)
    return jsonify({"error": "Not found"}), 404

@app.route("/api/section_defs/<sec_id>", methods=["DELETE"])
def delete_section_def(sec_id):
    data = load_data()
    data["section_defs"] = [sd for sd in data["section_defs"] if sd["id"] != sec_id]
    for t in data["templates"]:
        t["sections"] = [s for s in t.get("sections", []) if s != sec_id]
    save_data(data)
    return jsonify({"ok": True})


# Templates ───────────────────────────────────────────────────────────────────

@app.route("/api/templates", methods=["GET"])
def list_templates():
    return jsonify(load_data()["templates"])

@app.route("/api/templates", methods=["POST"])
def create_template():
    data = load_data()
    body = request.json
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


# Jobs ────────────────────────────────────────────────────────────────────────

@app.route("/api/jobs", methods=["GET"])
def list_jobs():
    return jsonify(load_data()["jobs"])

@app.route("/api/jobs", methods=["POST"])
def create_job():
    data = load_data()
    body = request.json
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


# Generate ────────────────────────────────────────────────────────────────────

@app.route("/api/generate", methods=["POST"])
def generate():
    body = request.json
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
            results.append({"job_id": job_id, "error": "Job not found"}); continue
        json_path = job.get("json_path", "")
        if not json_path:
            results.append({"job_id": job_id, "error": "No JSON path set"}); continue
        json_file = Path(json_path)
        if not json_file.exists():
            results.append({"job_id": job_id, "error": f"File not found: {json_path}"}); continue
        try:
            resume_data = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as e:
            results.append({"job_id": job_id, "error": f"JSON parse error: {e}"}); continue
        custom = job.get("output_name", "").strip()
        fname  = (custom if custom.endswith(".pdf") else custom + ".pdf") if custom else json_file.stem + ".pdf"
        out_path = output_dir / fname
        try:
            generate_pdf(resume_data, template, data["section_defs"], str(out_path))
            results.append({"job_id": job_id, "output": str(out_path), "ok": True})
        except Exception:
            tb = traceback.format_exc()
            print(tb, flush=True)
            results.append({"job_id": job_id, "error": tb})

    return jsonify({"results": results})


# Meta ────────────────────────────────────────────────────────────────────────

@app.route("/api/meta", methods=["GET"])
def meta():
    return jsonify({
        "section_types":   SECTION_TYPES,
        "available_fonts": list(AVAILABLE_FONTS.keys()),
        "font_variants":   AVAILABLE_FONTS,
    })


if __name__ == "__main__":
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        save_data(DEFAULT_DATA)
    app.run(host="0.0.0.0", port=8030, debug=False)
