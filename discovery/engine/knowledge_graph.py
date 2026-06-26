"""Knowledge Graph — Business glossary, terms, relationships.
Backed by Firestore in GCP, local YAML fallback for dev/testing."""
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BusinessTerm:
    id: str
    name: str
    domain: str
    synonyms: list[str] = field(default_factory=list)
    data_type: str = "string"
    information_type: str = "Dimension"
    is_pii: bool = False
    is_key_candidate: bool = False
    classification: str = "Internal"
    pattern: Optional[str] = None
    reference_code_set: Optional[str] = None
    dq_rules: dict = field(default_factory=dict)


@dataclass
class BusinessApplication:
    id: str
    name: str
    description: str
    keywords: list[str] = field(default_factory=list)


@dataclass
class DataDomain:
    id: str
    name: str
    description: str


@dataclass
class DataElement:
    name: str
    data_type: str
    description: str
    maps_to: str  # business term id


@dataclass
class DatasetDefinition:
    name: str
    source_application: str
    data_elements: list[str] = field(default_factory=list)


@dataclass
class GovernanceRule:
    id: str
    applies_to: str
    rule_type: str
    condition: str
    severity: str = "medium"


class KnowledgeGraph:
    """In-memory knowledge graph loaded from seed glossary + banking catalog.
    Production: swap with Firestore backend."""

    def __init__(self, seed_path: Optional[str] = None, catalog_dir: Optional[str] = None):
        self.terms: dict[str, BusinessTerm] = {}
        self.applications: dict[str, BusinessApplication] = {}
        self.domains: dict[str, DataDomain] = {}
        self.reference_code_sets: dict[str, list] = {}
        self.classifications: list[dict] = []
        self.data_elements: dict[str, DataElement] = {}
        self.datasets: dict[str, DatasetDefinition] = {}
        self.governance_rules: list[GovernanceRule] = []

        config_dir = Path(__file__).parent.parent / "config"

        if seed_path is None:
            seed_path = str(config_dir / "seed_glossary.yaml")
        self._load_from_yaml(seed_path)

        # Load banking catalog files if present
        if catalog_dir is None:
            catalog_dir = str(config_dir)
        self._load_banking_catalog(catalog_dir)

    def _load_from_yaml(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        for app in data.get("business_applications", []):
            self.applications[app["id"]] = BusinessApplication(
                id=app["id"], name=app["name"],
                description=app["description"], keywords=app.get("keywords", [])
            )

        for domain in data.get("data_domains", []):
            self.domains[domain["id"]] = DataDomain(
                id=domain["id"], name=domain["name"], description=domain["description"]
            )

        for term in data.get("business_terms", []):
            self.terms[term["id"]] = BusinessTerm(
                id=term["id"], name=term["name"], domain=term["domain"],
                synonyms=term.get("synonyms", []),
                data_type=term.get("data_type", "string"),
                information_type=term.get("information_type", "Dimension"),
                is_pii=term.get("is_pii", False),
                is_key_candidate=term.get("is_key_candidate", False),
                classification=term.get("classification", "Internal"),
                pattern=term.get("pattern"),
                reference_code_set=term.get("reference_code_set"),
                dq_rules=term.get("dq_rules", {}),
            )

        self.reference_code_sets = data.get("reference_code_sets", {})
        self.classifications = data.get("data_classifications", [])

    def search_by_synonym(self, field_name: str) -> list[tuple[BusinessTerm, float]]:
        """Find terms where field_name matches a synonym. Returns (term, confidence)."""
        field_lower = field_name.lower().strip()
        matches = []

        for term in self.terms.values():
            for synonym in term.synonyms:
                if field_lower == synonym.lower():
                    matches.append((term, 0.95))
                    break
                elif field_lower in synonym.lower() or synonym.lower() in field_lower:
                    # Partial match
                    overlap = len(set(field_lower.split("_")) & set(synonym.lower().split("_")))
                    max_parts = max(len(field_lower.split("_")), len(synonym.lower().split("_")))
                    confidence = overlap / max_parts if max_parts > 0 else 0
                    if confidence >= 0.5:
                        matches.append((term, round(confidence * 0.9, 2)))
                        break

        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[:3]

    def search_by_domain_keywords(self, text: str) -> list[tuple[BusinessApplication, float]]:
        """Match text against business application keywords."""
        text_lower = text.lower()
        words = set(text_lower.replace("_", " ").replace("-", " ").split())
        matches = []

        for app in self.applications.values():
            overlap = words & set(app.keywords)
            if overlap:
                confidence = len(overlap) / max(len(words), 1)
                matches.append((app, round(min(confidence * 1.5, 0.95), 2)))

        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[:3]

    def get_reference_set(self, set_id: str) -> Optional[list]:
        return self.reference_code_sets.get(set_id)

    def add_term(self, term: BusinessTerm):
        """Add a new term (from steward approval of SD suggestion)."""
        self.terms[term.id] = term

    def asset_exists(self, asset_name: str) -> bool:
        """Check if we've seen this asset before (simplified — check if any term references it)."""
        # In production, this checks Firestore/Dataplex catalog
        return False

    def get_all_terms(self) -> list[BusinessTerm]:
        return list(self.terms.values())

    def get_terms_by_domain(self, domain_id: str) -> list[BusinessTerm]:
        return [t for t in self.terms.values() if t.domain == domain_id]

    def _load_banking_catalog(self, catalog_dir: str):
        """Load banking catalog files (business_applications, glossary, data_elements, etc.)"""
        catalog_path = Path(catalog_dir)

        # Business Applications
        apps_file = catalog_path / "business_applications.yaml"
        if apps_file.exists():
            with open(apps_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            for app in data.get("business_applications", []):
                app_id = app["id"].lower()
                # Derive keywords from name + description + domain
                keywords = (app.get("name", "") + " " + app.get("description", "") + " " + app.get("domain", "")).lower().split()
                self.applications[app_id] = BusinessApplication(
                    id=app_id, name=app["name"],
                    description=app.get("description", ""),
                    keywords=keywords,
                )

        # Business Glossary
        glossary_file = catalog_path / "business_glossary.yaml"
        if glossary_file.exists():
            with open(glossary_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            for term in data.get("business_glossary", []):
                term_id = term["id"].lower()
                domain = term.get("domain", "general").lower()
                # Add domain if not exists
                if domain not in self.domains:
                    self.domains[domain] = DataDomain(
                        id=domain, name=domain.title(), description=f"{domain.title()} domain"
                    )
                # Create business term with name-derived synonyms
                name_lower = term["name"].lower()
                synonyms = [name_lower, name_lower.replace(" ", "_")]
                self.terms[term_id] = BusinessTerm(
                    id=term_id, name=term["name"], domain=domain,
                    synonyms=synonyms,
                    information_type="Dimension",
                    dq_rules={},
                )

        # Business Data Elements
        elements_file = catalog_path / "business_data_elements.yaml"
        if elements_file.exists():
            with open(elements_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            for elem in data.get("business_data_elements", []):
                self.data_elements[elem["name"]] = DataElement(
                    name=elem["name"],
                    data_type=elem.get("data_type", "string"),
                    description=elem.get("description", ""),
                    maps_to=elem.get("maps_to", ""),
                )
                # Also enrich the corresponding term's synonyms
                maps_to = elem.get("maps_to", "").lower()
                if maps_to in self.terms:
                    if elem["name"] not in self.terms[maps_to].synonyms:
                        self.terms[maps_to].synonyms.append(elem["name"])

        # Dataset Definitions
        datasets_file = catalog_path / "dataset_definitions.yaml"
        if datasets_file.exists():
            with open(datasets_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            for ds in data.get("datasets", []):
                self.datasets[ds["name"]] = DatasetDefinition(
                    name=ds["name"],
                    source_application=ds.get("source_application", ""),
                    data_elements=ds.get("data_elements", []),
                )

        # Governance Rules
        rules_file = catalog_path / "governance_rules.yaml"
        if rules_file.exists():
            with open(rules_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            for rule in data.get("governance_rules", []):
                self.governance_rules.append(GovernanceRule(
                    id=rule["id"],
                    applies_to=rule.get("applies_to", ""),
                    rule_type=rule.get("rule_type", "validation"),
                    condition=rule.get("condition", ""),
                    severity=rule.get("severity", "medium"),
                ))

    def get_governance_rules_for_field(self, field_name: str) -> list[GovernanceRule]:
        """Find governance rules that apply to a field."""
        return [r for r in self.governance_rules if r.applies_to == field_name]

    def get_dataset(self, name: str) -> Optional[DatasetDefinition]:
        return self.datasets.get(name)

    def get_application_by_id(self, app_id: str) -> Optional[BusinessApplication]:
        return self.applications.get(app_id.lower())
