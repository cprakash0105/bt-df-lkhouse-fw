"""Test SD Intent Routing — Simulates user prompts and checks which handler would be triggered.

Run: python discovery/tests/test_intent_routing.py

Tests the frontend routing logic (replicated in Python) to ensure prompts go to the right handler.
"""

# Replicate the frontend routing logic
def classify_intent(text):
    """Replicate App.jsx routing logic."""
    lower = text.lower().strip()

    # 1. Landing list — only if explicitly about landing zone or asking what's available to onboard
    if (('available' in lower and 'landing' in lower) or
        ('landing' in lower and 'list' in lower) or
        (lower in ("what's available", "what's available?", "whats available")) or
        ('available' in lower and 'dataset' in lower) or
        ('available' in lower and not any(w in lower for w in ['business app', 'business application', 'domain', 'bde', 'term']))):
        return "LANDING_LIST"

    # 2. Approve
    if lower in ('approve', 'approve all') or ('approve' in lower and 'business' not in lower):
        return "APPROVE"

    # 3. Generate config
    if ('config' in lower or 'yaml' in lower) and 'generate' not in lower:
        return "GENERATE_CONFIG"
    if 'generate' in lower and ('config' in lower or 'yaml' in lower):
        return "GENERATE_CONFIG"
    if lower in ('show config', 'generate config', 'generate the yaml'):
        return "GENERATE_CONFIG"

    # 4. Corrections (must check before questions)
    if is_correction(lower):
        return "CORRECTION"

    # 5. Glossary/BA/Domain questions (catalog-level, not about current discovery)
    if is_glossary_question(lower) and not _is_field_specific_question(lower):
        return "GLOSSARY_QUESTION"

    # 6. Questions about current results
    if is_question(lower):
        return "RESULT_QUESTION"

    # 7. Default: discover
    return "DISCOVER"


def _is_field_specific_question(text):
    """Check if it's a question about a specific field in current results."""
    # "why is X marked as PII" / "why did you mark X as PII" → result question, not glossary
    if ('marked' in text or 'why is' in text or 'why did' in text) and \
       any(w in text for w in ['pii', 'unique', 'key', 'null']):
        return True
    return False


def is_glossary_question(text):
    return ('business application' in text or 'business app' in text or
            'how many' in text or 'bde' in text or 'glossary' in text or
            ('domain' in text and any(w in text for w in ['how', 'what', 'which', 'tell', 'show', 'list'])) or
            ('terms' in text and any(w in text for w in ['how many', 'list', 'show'])) or
            'pii' in text or 'dq rule' in text or 'data quality' in text or
            'who owns' in text or 'relationship' in text or 'linked' in text or
            'catalog' in text or 'search for' in text or
            ('list' in text and any(w in text for w in ['application', 'domain', 'term', 'dataset'])))


def is_question(text):
    question_words = ['did you', 'can you tell', 'what is', 'what are', 'why', 'how',
                      'which', 'show me', 'explain', 'tell me', 'is there', 'was the',
                      'were the', 'has the', 'profile', 'fingerprint', 'confidence',
                      'reasoning', 'why did']
    # "what about X" is a discover request, not a question
    if 'what about' in text or 'how about' in text:
        return False
    return any(q in text for q in question_words) or text.endswith('?')


def is_correction(text):
    return ('is not pii' in text or 'is pii' in text or
            'is not unique' in text or 'is unique' in text or
            'is nullable' in text or 'not null' in text or
            'values are' in text or 'values should' in text or
            'maps to' in text or 'remove ' in text)


# --- TEST CASES ---

TESTS = [
    # Glossary/BA/Domain questions → should route to GLOSSARY_QUESTION
    ("List all the business applications", "GLOSSARY_QUESTION"),
    ("list all business applications", "GLOSSARY_QUESTION"),
    ("What business applications are in Credit domain?", "GLOSSARY_QUESTION"),
    ("How many business applications are there?", "GLOSSARY_QUESTION"),
    ("Show me the domains", "GLOSSARY_QUESTION"),
    ("What domains do we have?", "GLOSSARY_QUESTION"),
    ("List all domains", "GLOSSARY_QUESTION"),
    ("How many BDEs are in the Customer domain?", "GLOSSARY_QUESTION"),
    ("Tell me about the glossary", "GLOSSARY_QUESTION"),
    ("What BDEs exist?", "GLOSSARY_QUESTION"),
    ("Which fields are PII?", "GLOSSARY_QUESTION"),
    ("Show PII fields", "GLOSSARY_QUESTION"),
    ("What DQ rules apply to Credit Score?", "GLOSSARY_QUESTION"),
    ("What data quality rules exist?", "GLOSSARY_QUESTION"),
    ("Who owns the CIBIL feed?", "GLOSSARY_QUESTION"),
    ("Can you pull the list of datasets from Knowledge Catalog?", "GLOSSARY_QUESTION"),
    ("Search for terms related to payment", "GLOSSARY_QUESTION"),
    ("What is linked to Customer ID?", "GLOSSARY_QUESTION"),
    ("How many terms are in the glossary?", "GLOSSARY_QUESTION"),
    ("List all datasets in the catalog", "GLOSSARY_QUESTION"),
    ("Tell me about the Credit Risk business application", "GLOSSARY_QUESTION"),
    ("What business apps are available?", "GLOSSARY_QUESTION"),

    # Landing list → should route to LANDING_LIST
    ("What's available in landing?", "LANDING_LIST"),
    ("Show what's available", "LANDING_LIST"),
    ("What datasets are available?", "LANDING_LIST"),
    ("List landing datasets", "LANDING_LIST"),

    # Discover → should route to DISCOVER
    ("Onboard customer complaints", "DISCOVER"),
    ("Discover the CIBIL bureau feed", "DISCOVER"),
    ("I want to onboard the loan repayment schedule", "DISCOVER"),
    ("Let's onboard UPI transactions", "DISCOVER"),
    ("Load the eKYC feed", "DISCOVER"),
    ("Process motor policy", "DISCOVER"),
    ("onboard card transactions", "DISCOVER"),
    ("customer_complaints", "DISCOVER"),
    ("cibil_bureau_feed", "DISCOVER"),

    # Corrections → should route to CORRECTION
    ("status is not PII", "CORRECTION"),
    ("sub_category is not PII", "CORRECTION"),
    ("customer_id is unique", "CORRECTION"),
    ("resolution_date is not PII", "CORRECTION"),
    ("priority values are low, medium, high, critical", "CORRECTION"),
    ("status values should be open, closed, pending", "CORRECTION"),
    ("remove description from not_null", "CORRECTION"),
    ("due_date is nullable", "CORRECTION"),

    # Approve → should route to APPROVE
    ("approve", "APPROVE"),
    ("approve all", "APPROVE"),
    ("yes, approve it", "APPROVE"),

    # Generate config → should route to GENERATE_CONFIG
    ("show config", "GENERATE_CONFIG"),
    ("generate the yaml", "GENERATE_CONFIG"),
    ("generate config", "GENERATE_CONFIG"),

    # Questions about results → should route to RESULT_QUESTION
    ("Can you tell me if data was profiled?", "RESULT_QUESTION"),
    ("Why is resolution_date marked as PII?", "RESULT_QUESTION"),
    ("What is the confidence for status?", "RESULT_QUESTION"),
    ("Did you fingerprint the data?", "RESULT_QUESTION"),
    ("Explain the reasoning for complaint_id", "RESULT_QUESTION"),
    ("How was the primary key determined?", "RESULT_QUESTION"),

    # Edge cases — should NOT go to wrong handler
    ("list all the business application", "GLOSSARY_QUESTION"),  # NOT landing
    ("show me business apps in the Credit domain", "GLOSSARY_QUESTION"),  # NOT discover
    ("what about motor claims?", "DISCOVER"),  # should discover, not question
    ("onboard all insurance datasets", "DISCOVER"),  # should discover
]


def run_tests():
    passed = 0
    failed = 0
    failures = []

    for prompt, expected in TESTS:
        actual = classify_intent(prompt)
        if actual == expected:
            passed += 1
        else:
            failed += 1
            failures.append((prompt, expected, actual))

    print(f"\n{'='*60}")
    print(f"INTENT ROUTING TESTS: {passed}/{len(TESTS)} passed, {failed} failed")
    print(f"{'='*60}\n")

    if failures:
        print("FAILURES:")
        print("-" * 60)
        for prompt, expected, actual in failures:
            print(f"  PROMPT:    \"{prompt}\"")
            print(f"  EXPECTED:  {expected}")
            print(f"  ACTUAL:    {actual}")
            print()

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
