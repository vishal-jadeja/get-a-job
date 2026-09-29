"""Editable, evidence-based role suggestions. No model or paid API required."""
from .matching import contains
from .skills import has_skill

ROLE_SKILLS = {
    "Frontend Engineer": ["javascript", "typescript", "react", "vue", "angular", "css", "html", "next.js"],
    "Backend Engineer": ["python", "java", "go", "node.js", "django", "fastapi", "spring", "postgresql", "rest", "sql"],
    "Full Stack Engineer": ["react", "typescript", "node.js", "python", "postgresql", "next.js", "django"],
    "Software Engineer": ["python", "java", "javascript", "typescript", "go", "c++", "c#", "rust", "sql"],
    "Mobile Engineer": ["swift", "kotlin", "android", "ios", "flutter", "react native", "dart"],
    "Data Analyst": ["sql", "excel", "tableau", "power bi", "python", "statistics", "analytics"],
    "Data Scientist": ["python", "statistics", "machine learning", "pandas", "scikit-learn", "r", "experimentation"],
    "Data Engineer": ["sql", "python", "spark", "airflow", "dbt", "snowflake", "etl", "kafka"],
    "Machine Learning Engineer": ["python", "pytorch", "tensorflow", "machine learning", "mlops", "llm", "transformers"],
    "DevOps Engineer": ["docker", "kubernetes", "terraform", "aws", "linux", "ci/cd", "ansible"],
    "Site Reliability Engineer": ["linux", "kubernetes", "prometheus", "grafana", "incident response", "terraform", "go"],
    "Cloud Engineer": ["aws", "azure", "gcp", "terraform", "networking", "linux"],
    "QA Engineer": ["selenium", "playwright", "cypress", "testing", "test automation", "pytest", "quality assurance"],
    "Security Engineer": ["cybersecurity", "penetration testing", "owasp", "siem", "network security", "security"],
    "Product Manager": ["product management", "roadmap", "user research", "analytics", "stakeholder management", "agile"],
    "Project Manager": ["project management", "agile", "scrum", "jira", "budgeting", "stakeholder management"],
    "Product Designer": ["figma", "user research", "ux", "ui", "prototyping", "design systems"],
    "Graphic Designer": ["photoshop", "illustrator", "graphic design", "branding", "indesign", "typography"],
    "Business Analyst": ["business analysis", "excel", "sql", "requirements gathering", "process improvement", "power bi"],
    "Marketing Specialist": ["marketing", "seo", "content marketing", "google analytics", "copywriting", "social media"],
    "Content Writer": ["writing", "copywriting", "seo", "editing", "content strategy", "journalism"],
    "Sales Representative": ["sales", "crm", "salesforce", "lead generation", "negotiation", "prospecting"],
    "Customer Success Manager": ["customer success", "account management", "crm", "onboarding", "retention"],
    "Customer Support Specialist": ["customer support", "zendesk", "troubleshooting", "customer service", "communication"],
    "Recruiter": ["recruiting", "sourcing", "talent acquisition", "interviewing", "human resources"],
    "Financial Analyst": ["financial modeling", "excel", "finance", "accounting", "forecasting", "valuation"],
    "Accountant": ["accounting", "bookkeeping", "quickbooks", "tax", "reconciliation", "excel"],
    "Operations Manager": ["operations", "logistics", "supply chain", "process improvement", "inventory", "budgeting"],
    "Technical Writer": ["technical writing", "documentation", "api", "editing", "markdown"],
    "Research Scientist": ["research", "statistics", "publications", "experiments", "python", "matlab"],
}


def suggest_roles(profile):
    evidence = "\n".join(profile.get("skills", []) + profile.get("technologies", []) +
                         profile.get("experience", []) + profile.get("projects", []) +
                         [profile.get("headline", ""), profile.get("resume_text", "")])
    suggestions = []
    for role, skills in ROLE_SKILLS.items():
        found = [s for s in skills if has_skill(evidence, s)]
        if len(found) >= 2:
            suggestions.append({"role": role, "evidence": found, "coverage": round(100 * len(found) / len(skills))})
    return sorted(suggestions, key=lambda x: (-x["coverage"], -len(x["evidence"]), x["role"]))[:8]
