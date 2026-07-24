"""Catalog Reader — Reads business terms from Google Dataplex Catalog.
Replaces local YAML loading in production. Falls back to YAML if Dataplex unavailable."""
import os
from typing import Optional
from dataclasses import dataclass, field

try:
    from google.cloud import dataplex_v1
    DATAPLEX_AVAILABLE = True
except ImportError:
    DATAPLEX_AVAILABLE = False


@dataclass
class CatalogTerm:
    id: str
    name: str
    domain: str = ""
    description: str = ""
    synonyms: list[str] = field(default_factory=list)
    data_type: str = "string"
    information_type: str = "Dimension"
    is_pii: bool = False
    is_key_candidate: bool = False
    classification: str = "Internal"
    pattern: Optional[str] = None
    reference_code_set: Optional[str] = None
    dq_rules: dict = field(default_factory=dict)


class CatalogReader:
    """Reads from Dataplex Catalog. Falls back to empty if unavailable."""

    def __init__(self, project_id: Optional[str] = None, location: str = "europe-west2",
                 glossary_id: str = "enterprise-data-glossary"):
        self.project_id = project_id or os.environ.get("GCP_PROJECT_ID", "bt-df-lkhouse")
        self.location = location
        self.glossary_id = glossary_id
        self._client = None

    def _get_client(self):
        if not DATAPLEX_AVAILABLE:
            return None
        if self._client is None:
            try:
                self._client = dataplex_v1.CatalogServiceClient()
            except Exception:
                return None
        return self._client

    def read_all_terms(self) -> list[CatalogTerm]:
        """Read all business terms from Dataplex Glossary."""
        client = self._get_client()
        if not client:
            return []

        glossary_name = (
            f"projects/{self.project_id}/locations/{self.location}"
            f"/glossaries/{self.glossary_id}"
        )

        terms = []
        try:
            request = dataplex_v1.ListGlossaryTermsRequest(parent=glossary_name)
            for term in client.list_glossary_terms(request=request):
                catalog_term = self._parse_term(term)
                if catalog_term:
                    terms.append(catalog_term)
        except Exception as e:
            print(f"[CatalogReader] Failed to read from Dataplex: {e}")
            return []

        return terms

    def read_categories(self) -> list[dict]:
        """Read all categories (domains) from the glossary."""
        client = self._get_client()
        if not client:
            return []

        glossary_name = (
            f"projects/{self.project_id}/locations/{self.location}"
            f"/glossaries/{self.glossary_id}"
        )

        categories = []
        try:
            request = dataplex_v1.ListGlossaryCategoriesRequest(parent=glossary_name)
            for cat in client.list_glossary_categories(request=request):
                categories.append({
                    "id": cat.name.split("/")[-1],
                    "name": cat.display_name,
                    "description": cat.description or "",
                })
        except Exception as e:
            print(f"[CatalogReader] Failed to read categories: {e}")

        return categories

    def write_term(self, term: CatalogTerm) -> bool:
        """Write a new term back to Dataplex (after steward approval)."""
        client = self._get_client()
        if not client:
            return False

        glossary_name = (
            f"projects/{self.project_id}/locations/{self.location}"
            f"/glossaries/{self.glossary_id}"
        )

        description_parts = []
        if term.information_type:
            description_parts.append(f"Information Type: {term.information_type}")
        if term.is_pii:
            description_parts.append("Classification: PII")
        if term.synonyms:
            description_parts.append(f"Synonyms: {', '.join(term.synonyms)}")
        if term.data_type:
            description_parts.append(f"Data Type: {term.data_type}")
        if term.dq_rules:
            description_parts.append(f"DQ Rules: {term.dq_rules}")

        glossary_term = dataplex_v1.GlossaryTerm(
            description=" | ".join(description_parts),
            display_name=term.name,
        )

        try:
            operation = client.create_glossary_term(
                parent=glossary_name,
                glossary_term=glossary_term,
                glossary_term_id=term.id,
            )
            operation.result()
            print(f"[CatalogReader] Written term to Dataplex: {term.name}")
            return True
        except Exception as e:
            print(f"[CatalogReader] Failed to write term '{term.name}': {e}")
            return False

    def _parse_term(self, dataplex_term) -> Optional[CatalogTerm]:
        """Parse a Dataplex GlossaryTerm into our CatalogTerm format."""
        term_id = dataplex_term.name.split("/")[-1]
        name = dataplex_term.display_name or term_id
        description = dataplex_term.description or ""

        # Parse structured data from description (we encode it there)
        synonyms = []
        data_type = "string"
        information_type = "Dimension"
        is_pii = False
        classification = "Internal"
        dq_rules = {}
        pattern = None
        reference_code_set = None

        domain = ""
        for part in description.split(" | "):
            part = part.strip()
            if part.startswith("Synonyms:"):
                synonyms = [s.strip() for s in part[9:].split(",")]
            elif part.startswith("Data Type:"):
                data_type = part[10:].strip()
            elif part.startswith("Information Type:"):
                information_type = part[17:].strip()
            elif part.startswith("Classification: PII"):
                is_pii = True
                classification = "PII"
            elif part.startswith("Classification:"):
                classification = part[15:].strip()
            elif part.startswith("DQ Rules:"):
                try:
                    import ast
                    dq_rules = ast.literal_eval(part[9:].strip())
                except Exception:
                    pass
            elif part.startswith("Pattern:"):
                pattern = part[8:].strip()
            elif part.startswith("Reference Set:"):
                reference_code_set = part[14:].strip()
            elif part.startswith("Domain:"):
                domain = part[7:].strip()

        # Also derive synonyms from name
        name_lower = name.lower()
        if name_lower not in synonyms:
            synonyms.append(name_lower)
        name_underscore = name_lower.replace(" ", "_")
        if name_underscore not in synonyms:
            synonyms.append(name_underscore)

        return CatalogTerm(
            id=term_id,
            name=name,
            domain=domain,
            description=description,
            synonyms=synonyms,
            data_type=data_type,
            information_type=information_type,
            is_pii=is_pii,
            is_key_candidate=(information_type == "Identifier"),
            classification=classification,
            pattern=pattern,
            reference_code_set=reference_code_set,
            dq_rules=dq_rules,
        )
