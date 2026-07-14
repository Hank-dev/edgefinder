from __future__ import annotations

import re
from functools import lru_cache

TAXONOMY: dict[str, dict[str, list[str]]] = {
    "Programming": {
        "Python": ["python"],
        "Java": ["java"],
        "JavaScript": ["javascript", "js"],
        "TypeScript": ["typescript"],
        "C++": ["c++"],
        "C#": ["c#", ".net", "dotnet"],
        "Go": ["golang", "go"],
        "Rust": ["rust"],
        "React": ["react", "react.js", "reactjs"],
        "Vue": ["vue", "vuejs"],
        "Node.js": ["node", "node.js", "nodejs"],
        "API-design": ["rest", "graphql", "api"],
        "Git": ["git", "github", "gitlab"],
    },
    "Data & ML": {
        "SQL": ["sql", "postgresql", "postgres", "mysql", "tsql"],
        "Machine Learning": ["machine learning", "maskinlæring", "ml"],
        "AI": ["ai", "kunstig intelligens", "llm", "genai"],
        "Data Engineering": ["data engineer", "dataplattform", "etl", "data pipeline", "datavarehus", "data warehouse"],
        "dbt": ["dbt"],
        "Spark": ["spark", "databricks"],
        "Snowflake": ["snowflake"],
        "Pandas": ["pandas"],
        "PyTorch": ["pytorch"],
        "TensorFlow": ["tensorflow"],
        "Power BI": ["power bi", "powerbi"],
        "Tableau": ["tableau"],
        "Analyse": ["analytics", "analyse", "statistikk", "statistics"],
        "Kafka": ["kafka"],
    },
    "Cloud & Infra": {
        "Azure": ["azure"],
        "AWS": ["aws", "amazon web services"],
        "GCP": ["gcp", "google cloud"],
        "Kubernetes": ["kubernetes", "k8s"],
        "Docker": ["docker", "container"],
        "Terraform": ["terraform"],
        "Linux": ["linux"],
        "CI/CD": ["ci/cd", "cicd", "jenkins", "github actions"],
        "DevOps": ["devops", "sre", "platform engineering"],
        "Sikkerhet": ["sikkerhet", "security", "cyber", "iam"],
    },
    "Finance & Econ": {
        "Regnskap": ["regnskap", "accounting", "bokføring", "regnskapsfører"],
        "Revisjon": ["revisjon", "audit", "revisor"],
        "Skatt": ["skatt", "tax", "mva", "vat"],
        "Controlling": ["controller", "controlling"],
        "Økonomistyring": ["økonomistyring", "budsjett", "budget", "forecasting", "prognose"],
        "Finans": ["finans", "finance", "investering", "investment", "kapitalforvaltning", "portfolio"],
        "Risk & Compliance": ["risk", "compliance", "kreditt", "aml"],
        "Excel": ["excel", "power query", "vba"],
        "SAP": ["sap"],
        "Visma": ["visma", "tripletex", "poweroffice"],
    },
    "Business & Methods": {
        "Prosjektledelse": ["prosjektledelse", "prosjektleder", "project manager", "pmp", "prince2"],
        "Agile": ["agile", "scrum", "kanban", "smidig"],
        "Produktledelse": ["product owner", "product manager", "produkteier"],
        "Forretningsutvikling": ["forretningsutvikling", "business development", "strategi", "strategy"],
        "Konsulentarbeid": ["konsulent", "consultant", "rådgiver", "rådgivning"],
        "Analytiker": ["analytiker", "analyst", "business analyst"],
        "Salg": ["salg", "sales", "crm"],
        "Ledelse": ["ledelse", "personalansvar", "management"],
    },
    "Languages": {
        "Norsk": ["norsk", "norwegian", "skandinavisk", "scandinavian"],
        "Engelsk": ["engelsk", "english"],
        "Tysk": ["tysk", "german"],
    },
}

CLUSTERS: list[str] = list(TAXONOMY)


def compile_term(term: str) -> re.Pattern[str]:
    """Word-boundary match that survives æøå and symbol-bearing terms like c++ / c# / .net."""
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)


@lru_cache(maxsize=1)
def _compiled() -> list[tuple[str, str, re.Pattern[str]]]:
    return [
        (cluster, skill, compile_term(synonym))
        for cluster, skills in TAXONOMY.items()
        for skill, synonyms in skills.items()
        for synonym in synonyms
    ]


def extract_skills(text: str) -> set[tuple[str, str]]:
    return {(cluster, skill) for cluster, skill, pattern in _compiled() if pattern.search(text)}
