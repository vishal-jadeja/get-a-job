"""Generate Jake-style LaTeX from reviewed text; compile only our escaped source."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = Path(__file__).resolve().parent / 'templates'
SECTIONS = {'SKILLS': 'Technical Skills', 'SELECTED EXPERIENCE': 'Experience', 'EXPERIENCE': 'Experience',
            'PROJECTS': 'Projects', 'EDUCATION': 'Education', 'CERTIFICATIONS': 'Certifications',
            'ACHIEVEMENTS': 'Achievements', 'LANGUAGES': 'Languages', 'SUMMARY': 'Summary'}


def escape_latex(value):
    replacements = {'\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#',
                    '_': r'\_', '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}',
                    '•': r'\textbullet{}', '₹': 'INR ', '→': r'\ensuremath{\rightarrow}',
                    '—': '---', '–': '--', '\t': ' '}
    return ''.join(replacements.get(char, char) for char in str(value) if ord(char) >= 32 or char == '\n')


def render_latex(resume):
    if not isinstance(resume, str) or not resume.strip():
        raise ValueError('Prepare a résumé before generating LaTeX')
    blocks = [block.strip() for block in resume.replace('\r\n', '\n').split('\n\n') if block.strip()]
    first = blocks.pop(0).splitlines()
    name = first.pop(0)
    contact = '\n'.join(first) if first else (blocks.pop(0) if blocks and blocks[0].splitlines()[0] not in SECTIONS else '')
    body = [r'\begin{center}', r'\textbf{\Huge\scshape ' + escape_latex(name) + r'}\\[3pt]',
            r'\small ' + escape_latex(contact).replace('\n', r'\\ ') + r'\end{center}']
    for block in blocks:
        lines = block.splitlines()
        section = SECTIONS.get(lines[0].strip())
        if section:
            body.append(r'\section{' + section + '}')
            lines = lines[1:]
        if section in ('Experience', 'Projects', 'Education'):
            for line in lines:
                line = line.lstrip('• ').strip()
                header, separator, description = line.partition(' — ')
                pieces = [part.strip() for part in header.split(' | ')]
                if len(pieces) == 3:
                    body.append(r'\resumeSubheading{' + escape_latex(pieces[0]) + '}{' + escape_latex(pieces[1]) + '}{' + escape_latex(pieces[2]) + '}')
                    if separator:
                        body.extend([r'\begin{itemize}', r'\resumeItem{' + escape_latex(description) + '}', r'\end{itemize}'])
                    else:
                        body.append(r'\vspace{4pt}')
                else:
                    body.extend([r'\begin{itemize}', r'\resumeItem{' + escape_latex(line) + '}', r'\end{itemize}'])
        elif any(line.startswith('• ') for line in lines):
            body.append(r'\begin{itemize}')
            body.extend(r'\resumeItem{' + escape_latex(line.removeprefix('• ')) + '}' for line in lines)
            body.append(r'\end{itemize}')
        else:
            body.append(r'{\small ' + r'\\ '.join(escape_latex(line) for line in lines) + r'}\par\vspace{4pt}')
    template = (TEMPLATES / 'jake-resume.tex').read_text(encoding='utf-8')
    notice = '\n'.join('% ' + line for line in license_text().splitlines())
    return notice + '\n' + template.replace('%%JOBPILOT_BODY%%', '\n'.join(body))


def compiler():
    configured = os.environ.get('JOBPILOT_TECTONIC')
    portable = ROOT / '.tools' / 'tectonic' / ('tectonic.exe' if os.name == 'nt' else 'tectonic')
    for candidate in (configured, str(portable) if portable.is_file() else None, shutil.which('tectonic')):
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return None


def compile_pdf(resume):
    engine = compiler()
    if not engine:
        raise ValueError('Install Tectonic or set JOBPILOT_TECTONIC to its executable. You can still download LaTeX and compile it in Overleaf.')
    source = render_latex(resume)
    with tempfile.TemporaryDirectory(prefix='jobpilot-latex-') as directory:
        path = Path(directory)
        (path / 'resume.tex').write_text(source, encoding='utf-8')
        try:
            process = subprocess.run([engine, '--untrusted', '--keep-logs', '--outdir', directory, str(path / 'resume.tex')],
                                     cwd=directory, capture_output=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        except subprocess.TimeoutExpired:
            raise ValueError('PDF compilation timed out. Download the LaTeX source or try again after Tectonic has cached its packages.') from None
        output = path / 'resume.pdf'
        if process.returncode or not output.is_file():
            raise ValueError('PDF compilation failed. Check Tectonic network/package access and unsupported characters, or compile the downloaded source in Overleaf.')
        content = output.read_bytes()
        if not content.startswith(b'%PDF-'):
            raise ValueError('The compiler did not produce a valid PDF')
        return content


def license_text():
    return (TEMPLATES / 'LICENSE-jake.txt').read_text(encoding='utf-8')
