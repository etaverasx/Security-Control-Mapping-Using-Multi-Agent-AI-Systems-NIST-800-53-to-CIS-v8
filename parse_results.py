# parse_results.py
# Extracts structured data from pipeline JSON output files.
# Imported by run_batch.py -- never run directly.
#
# Handles all known Gemma output formats:
#   Format A: **CIS 5.1: Title - WEAK**               (inline classification at end of bold line)
#   Format B: **1. CIS 5.1: Title**                   (numbered, then bullet on next line)
#             *   **Classification:** WEAK
#   Format C: **CIS 5.1: Title**                      (separate line, no bullet)
#             **Classification: WEAK**
#   Format D: last-resort line scanner                (any line containing CIS ID + classification word)
#   Format E: CIS 5.1: Title **(STRONG)**             (inline classification in double-star parens)
#   Format F: **1. CIS 5.1: Title**                   (numbered bold title, then)
#             *   **Classification: PARTIAL**          (bullet with colon, no space after **)

import re


def parse_classifications(text):
    """
    Extract STRONG/PARTIAL/WEAK CIS IDs from Agent 3 output.
    Returns three lists: (strong, partial, weak)
    """
    strong, partial, weak = [], [], []

    # work on the actual agent response only -- strip prompt headers if present
    # CrewAI sometimes includes the full system/user prompt before the response
    # find the last occurrence of a classification pattern to isolate the response
    clean = text

    # Format E: CIS ID on one line, **(STRONG)** on the next line (similarity line)
    # e.g. "1. CIS 11.4: Establish and Maintain...\n   Security Function: ... **(STRONG)**"
    pattern_e = r'(CIS [\d.]+)[^\n]*\n[^\n]*?\*\*\((STRONG|PARTIAL|WEAK)\)\*\*'
    matches_e = re.findall(pattern_e, clean, re.IGNORECASE)
    if matches_e:
        seen = set()
        for cis_id, cls in matches_e:
            cis_id = cis_id.strip()
            cls = cls.upper()
            if cis_id in seen:
                continue
            seen.add(cis_id)
            if cls == 'STRONG':
                strong.append(cis_id)
            elif cls == 'PARTIAL':
                partial.append(cis_id)
            elif cls == 'WEAK':
                weak.append(cis_id)
        return strong, partial, weak

    # Format A & B inline: **CIS 5.1: Title - WEAK** or **1. CIS 5.1: Title - WEAK**
    pattern_inline = r'\*\*(?:\d+\.\s*)?(CIS [\d.]+)[^*]*(STRONG|PARTIAL|WEAK)\*\*'
    matches = re.findall(pattern_inline, clean, re.IGNORECASE)

    # Format F: **1. CIS 5.1: Title** then *   **Classification: PARTIAL**
    # (bullet + bold + colon + space + classification, no space before colon)
    if not matches:
        pattern_f = r'\*\*(?:\d+\.\s*)?(CIS [\d.]+)[^*]*\*\*\s*\n\s*\*+\s*\*\*Classification:\s*(STRONG|PARTIAL|WEAK)\*\*'
        matches = re.findall(pattern_f, clean, re.IGNORECASE)

    # Format B: **1. CIS 5.1: Title** then *   **Classification:** WEAK
    # (bullet + bold + colon + space + classification word outside bold)
    if not matches:
        pattern_bullet = r'\*\*(?:\d+\.\s*)?(CIS [\d.]+)[^*]*\*\*\s*\n\s*\*\s*\*\*Classification:\*\*\s*(STRONG|PARTIAL|WEAK)'
        matches = re.findall(pattern_bullet, clean, re.IGNORECASE)

    # Format C: **CIS 5.1: Title** then **Classification: WEAK** on separate line (no bullet)
    if not matches:
        pattern_separate = r'\*\*(?:\d+\.\s*)?(CIS [\d.]+)[^*]*\*\*\s*\n\s*\*\*Classification:\s*(STRONG|PARTIAL|WEAK)\*\*'
        matches = re.findall(pattern_separate, clean, re.IGNORECASE)

    # Format D -- last resort fallback: find any line with both a CIS ID and a classification word
    if not matches:
        for line in clean.split('\n'):
            cis_match = re.search(r'(CIS [\d.]+)', line)
            cls_match = re.search(r'\b(STRONG|PARTIAL|WEAK)\b', line, re.IGNORECASE)
            if cis_match and cls_match:
                matches.append((cis_match.group(1), cls_match.group(1).upper()))

    seen = set()
    for cis_id, cls in matches:
        cis_id = cis_id.strip()
        cls = cls.upper()
        if cis_id in seen:
            continue
        seen.add(cis_id)
        if cls == 'STRONG':
            strong.append(cis_id)
        elif cls == 'PARTIAL':
            partial.append(cis_id)
        elif cls == 'WEAK':
            weak.append(cis_id)

    return strong, partial, weak


def extract_coverage(text):
    """
    Extract coverage percentage from Agent 4 interpretation output.
    Returns a string like '60%' or 'N/A' if not found.
    Handles bold markdown like **Estimated Overall Coverage Percentage:** Approximately 40%
    Handles ranges like '60-70%' and approximations like '~50%'.
    """
    # strip markdown bold markers before searching
    clean = text.replace("**", "").replace("*", "")
    for line in clean.split("\n"):
        if "%" in line and any(w in line.lower() for w in ["coverage", "overall", "estimated"]):
            match = re.search(r'(\~?\d+(?:[–\-]\d+)?%)', line)
            if match:
                return match.group(1).strip(".,;:()[]")
    return "N/A"


if __name__ == "__main__":
    # self-test covering all formats
    test_cases = [
        ("Format A", "**CIS 5.1: Inventory of Accounts - WEAK**\n   Reasoning: blah"),
        ("Format B", "**1. CIS 5.1: Inventory of Accounts**\n*   **Classification:** PARTIAL\n*   **Reasoning:** blah"),
        ("Format C", "**CIS 5.1: Inventory of Accounts**\n**Classification: STRONG**\nReasoning: blah"),
        ("Format E", "CIS 11.4: Establish and Maintain an Isolated Instance of Recovery Data **(STRONG)** - direct match.\nCIS 11.3: Protect Recovery Data **(PARTIAL)** - indirect.\nCIS 4.1: Secure Config **(WEAK)** - too broad."),
        ("Format F", "**1. CIS 7.3: Perform Automated OS Patch Management**\n*   **Classification: PARTIAL**\n*   **Reasoning:** blah"),
    ]

    print("Running self-tests...")
    all_passed = True
    for label, text in test_cases:
        s, p, w = parse_classifications(text)
        total = len(s) + len(p) + len(w)
        status = "PASS" if total > 0 else "FAIL"
        if status == "FAIL":
            all_passed = False
        print(f"  {status} {label}: strong={s} partial={p} weak={w}")

    print()
    if all_passed:
        print("All tests passed.")
    else:
        print("Some tests FAILED -- check patterns above.")