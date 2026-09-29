"""Shared lexical skill aliases; no model or external service."""
import re
from functools import lru_cache

ALIASES = {
    'javascript': ['JavaScript', 'JS', 'ECMAScript'], 'typescript': ['TypeScript', 'TS'],
    'react': ['React', 'React.js', 'ReactJS'], 'node.js': ['Node.js', 'NodeJS', 'Node JS'],
    'next.js': ['Next.js', 'NextJS'], 'vue': ['Vue', 'Vue.js', 'VueJS'],
    'postgresql': ['PostgreSQL', 'Postgres'], 'aws': ['AWS', 'Amazon Web Services'],
    'gcp': ['GCP', 'Google Cloud', 'Google Cloud Platform'], 'azure': ['Azure', 'Microsoft Azure'],
    'kubernetes': ['Kubernetes', 'K8s'], 'machine learning': ['Machine Learning', 'ML'],
    'ci/cd': ['CI/CD', 'CI CD', 'continuous integration', 'continuous delivery'],
    'rest': ['REST', 'RESTful'], 'llm': ['LLM', 'LLMs', 'large language models'],
    'c#': ['C#', 'C Sharp'], 'c++': ['C++'], 'go': ['Golang', 'Go language'],
    'scikit-learn': ['scikit-learn', 'sklearn'], 'pytorch': ['PyTorch'],
    'power bi': ['Power BI', 'PowerBI'], 'ux': ['UX', 'user experience'],
    'ui': ['UI', 'user interface'], 'seo': ['SEO', 'search engine optimization'],
    'html': ['HTML', 'HTML5'], 'css': ['CSS', 'CSS3'], 'sql': ['SQL'],
    'rag': ['RAG', 'retrieval augmented generation', 'retrieval-augmented generation'],
    'mongodb': ['MongoDB'], 'redis': ['Redis'], 'pgvector': ['pgvector'],
    'express.js': ['Express.js', 'ExpressJS'], 'fastapi': ['FastAPI'],
    'prompt engineering': ['Prompt Engineering'], 'oauth': ['OAuth', 'OAuth 2.0'],
    'jwt': ['JWT', 'JSON Web Tokens'], 'github actions': ['GitHub Actions'],
    'vector search': ['Vector Search'], 'websockets': ['WebSockets', 'WebSocket'],
    'supabase': ['Supabase'], 'drizzle': ['Drizzle ORM'], 'bullmq': ['BullMQ'],
    'vercel': ['Vercel'], 'rbac': ['RBAC', 'role-based access control'],
}


def canonical(value):
    value = value.strip().casefold()
    for key, aliases in ALIASES.items():
        if value == key or value in [a.casefold() for a in aliases]:
            return key
    return value


@lru_cache(maxsize=2048)
def pattern(skill):
    options = ALIASES.get(skill, [skill])
    return re.compile(r'(?<![\w])(?:' + '|'.join(re.escape(x) for x in sorted(options, key=len, reverse=True)) + r')(?![\w])', re.I)


def has_skill(text, skill):
    skill = canonical(skill)
    if skill == 'go':
        return bool(pattern(skill).search(text) or re.search(r'\bGo\b', text) or re.search(r'\b(?:using|in|with) go\b', text, re.I))
    if skill == 'r':
        return bool(re.search(r'(?<!\w)R(?![\w&])', text) or re.search(r'\br programming\b', text, re.I))
    return bool(pattern(skill).search(text))


def vocabulary(extras=()):
    from .roles import ROLE_SKILLS
    return sorted({canonical(s) for group in ROLE_SKILLS.values() for s in group} | set(ALIASES) | {canonical(s) for s in extras if s.strip()})


def extract_skills(text, extras=()):
    return [s for s in vocabulary(extras) if has_skill(text, s)]
