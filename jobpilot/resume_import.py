"""Local text extraction with a reviewable, non-destructive profile proposal."""
import base64
import io
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from .skills import extract_skills

MAX_FILE = 5 * 1024 * 1024
MAX_TEXT = 100000
SECTIONS = {
    'experience': ['experience', 'work experience', 'professional experience', 'employment', 'employment history', 'work history', 'selected experience'],
    'projects': ['projects', 'personal projects', 'selected projects', 'academic projects'],
    'education': ['education', 'academic background', 'qualifications'],
    'certifications': ['certifications', 'certificates', 'licenses'],
    'achievements': ['achievements', 'awards', 'honors', 'publications', 'volunteering'],
    'languages': ['languages'], 'skills': ['skills', 'technical skills', 'technologies', 'tech stack', 'core competencies'],
    'summary': ['summary', 'profile', 'professional summary', 'about me', 'objective'],
}


def decode_file(name, encoded):
    if not isinstance(name, str) or Path(name).suffix.lower() not in ('.pdf', '.docx', '.txt', '.md'):
        raise ValueError('Choose a PDF, DOCX, TXT, or Markdown résumé')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception:
        raise ValueError('Invalid résumé file encoding') from None
    if not raw or len(raw) > MAX_FILE:
        raise ValueError('Résumé must be between 1 byte and 5 MB')
    return raw


def docx_text(raw):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = [i for i in archive.infolist() if re.fullmatch(r'word/(document|header\d+|footer\d+)\.xml', i.filename)]
            if not any(i.filename == 'word/document.xml' for i in members) or sum(i.file_size for i in members) > 8 * 1024 * 1024:
                raise ValueError('DOCX content is missing or too large to extract')
            paragraphs = []
            for member in sorted(members, key=lambda i: i.filename != 'word/document.xml'):
                content = archive.read(member)
                if b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
                    raise ValueError('Unsupported XML declarations in DOCX')
                root = ET.fromstring(content)
                ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                for paragraph in root.iter(ns+'p'):
                    line = ''.join(n.text or '' for n in paragraph.iter(ns+'t')).strip()
                    if line:
                        paragraphs.append(line)
            return '\n'.join(paragraphs)
    except (zipfile.BadZipFile, ET.ParseError, RuntimeError):
        raise ValueError('This file could not be read as a DOCX résumé') from None


def pdf_text(raw):
    if not raw.startswith(b'%PDF-'):
        raise ValueError('This file is not a PDF')
    with tempfile.TemporaryDirectory(prefix='jobpilot-resume-') as directory:
        source = Path(directory) / 'resume.pdf'
        target = Path(directory) / 'resume.txt'
        source.write_bytes(raw)
        command = shutil.which('pdftotext')
        if command:
            args = [command, '-layout', '-enc', 'UTF-8', '-f', '1', '-l', '30', str(source), str(target)]
        else:
            # Optional pypdf runs in a separate process to enforce a parse timeout.
            args = [sys.executable, '-c',
                    'from pypdf import PdfReader; import sys; from pathlib import Path; r=PdfReader(sys.argv[1]); '
                    'Path(sys.argv[2]).write_text("\\n".join((p.extract_text() or "") for p in r.pages[:30]),encoding="utf-8")',
                    str(source), str(target)]
        try:
            result = subprocess.run(args, capture_output=True, timeout=20, check=False)
        except subprocess.TimeoutExpired:
            raise ValueError('PDF extraction timed out. Export a simpler text-based PDF or paste your résumé text.') from None
        if result.returncode or not target.exists():
            raise ValueError('Cannot extract this PDF. It may be encrypted or damaged. Install Poppler/pypdf if needed, or paste its text.')
        if target.stat().st_size > 2 * MAX_TEXT:
            raise ValueError('Extracted PDF text is too large; use a shorter résumé')
        return target.read_text(encoding='utf-8')


def propose(text):
    text = text.replace('\x00', '').replace('\r\n', '\n').replace('\r', '\n')
    if len(text) > MAX_TEXT:
        raise ValueError('Extracted résumé exceeds 100,000 characters')
    raw_lines = [line for line in text.splitlines() if line.strip()]
    lines = [re.sub(r'\s+', ' ', line).strip() for line in raw_lines]
    if sum(c.isalpha() for c in text) < 20:
        raise ValueError('No readable résumé text found. Scanned/image PDFs need OCR first, or paste the text.')
    fields = {k: [] for k in ('skills', 'technologies', 'experience', 'projects', 'education', 'certifications', 'achievements', 'languages')}
    section, captured, bullet_indent = None, set(), None
    for index, line in enumerate(lines):
        heading = re.sub(r'^[#\s]+|[:\s]+$', '', line).casefold()
        found = next((key for key, names in SECTIONS.items() if heading in names), None)
        if found:
            section = found
            bullet_indent = None
            captured.add(index)
            continue
        if section in fields and section != 'skills':
            indent = len(raw_lines[index]) - len(raw_lines[index].lstrip())
            is_bullet = bool(re.match(r'^[-–—•*]\s+', line))
            if bullet_indent is not None and not is_bullet and indent > bullet_indent and fields[section]:
                fields[section][-1] += ' ' + line
            else:
                fields[section].append(line)
                bullet_indent = indent if is_bullet else None
            captured.add(index)
    fields['skills'] = extract_skills(text)
    email = re.search(r'[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}', text, re.I)
    if email:
        fields['email'] = email[0]
    linkedin = re.search(r'(?:https?://)?(?:www\.)?linkedin\.com/in/[\w%\-]+', text, re.I)
    if linkedin:
        fields['linkedin'] = 'https://' + re.sub(r'^https?://', '', linkedin[0])
    website = re.search(r'(?:https?://)?(?:www\.)?github\.com/[\w-]+', text, re.I)
    if website and 'linkedin.com' not in website[0]:
        fields['website'] = 'https://' + re.sub(r'^https?://', '', website[0].rstrip('.,;'))
    phone = re.search(r'(?<!\w)\+\d[\d ()-]{7,20}\d(?!\w)', text) or re.search(r'(?<!\w)(?:\(?\d{3}\)?[ .-])?\d{3}[ .-]\d{4}(?!\w)', text)
    if phone:
        fields['phone'] = phone[0]
    for line in lines[:4]:
        if 2 <= len(line.split()) <= 5 and len(line) < 65 and not re.search(r'[@\d:/|]', line) and line.casefold() not in sum(SECTIONS.values(), []):
            fields['name'] = line
            break
    # Never calculate experience duration from dates or split legal names automatically.
    remaining = [line for i, line in enumerate(lines) if i not in captured and line != fields.get('name') and not (email and email[0] in line)]
    fields['resume_text'] = '\n'.join(remaining)[:30000]
    return {'fields': fields, 'text': text, 'warnings': [
        'Review every suggestion before importing. Columns and unfamiliar headings can be misread.',
        'Experience years, legal name parts, location eligibility, and authorization are not inferred.',
        'The original résumé attachment is unchanged; selected suggestions are merged into your profile.'
    ], 'extracted_lines': len(lines)}


def preview(name, encoded):
    raw = decode_file(name, encoded)
    suffix = Path(name).suffix.lower()
    if suffix == '.pdf':
        text = pdf_text(raw)
    elif suffix == '.docx':
        text = docx_text(raw)
    else:
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise ValueError('Save text résumés as UTF-8, or import PDF/DOCX') from None
    result = propose(text)
    result['filename'] = Path(name).name
    return result
