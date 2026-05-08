# test_pipeline.py
# Run this to test the pipeline on individual controls before the batch run.
# Automatically saves a JSON and PDF for each control run.

import json
import os
from datetime import datetime
from agents import nist_controls, run_mapping_pipeline, TEST_RUNS_PATH
from generate_pdf import generate_report

def run_test(control_id):
    print("\n" + "=" * 60)
    print(f"TESTING PIPELINE ON {control_id}")
    print("=" * 60 + "\n")

    control = next((c for c in nist_controls if c["id"] == control_id), None)
    if control is None:
        print(f"ERROR: {control_id} not found in nist_controls_parsed.json")
        return None

    result = run_mapping_pipeline(control)

    # save JSON and PDF with matching timestamps
    os.makedirs(TEST_RUNS_PATH, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{control_id}_pipeline_{timestamp}"

    # JSON
    json_path = os.path.join(TEST_RUNS_PATH, f"{base_name}.json")
    try:
        with open(json_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\n  JSON saved: {json_path} ({os.path.getsize(json_path)} bytes)")
    except Exception as e:
        print(f"\n  ERROR saving JSON: {e}")

    # PDF
    pdf_path = os.path.join(TEST_RUNS_PATH, f"{base_name}.pdf")
    try:
        generate_report(result, pdf_path)
    except Exception as e:
        print(f"  ERROR generating PDF: {e}")

    print(f"  Time: {result['elapsed_seconds']}s")
    print("\n=== VERIFIED SEARCH RESULTS ===")
    print(result["verified_search_results"])
    print("\n=== MAPPING CLASSIFICATION (Agent 3) ===")
    print(result["mapping_classification"])
    print("\n=== FINAL INTERPRETATION (Agent 4) ===")
    print(result["interpretation"])

    return result


# ============================================================
# Add controls to test below -- each one gets its own JSON + PDF
# Ground truth for reference:
#   AC-2    -- CIS 5.1, 5.5, 6.1, 6.2, 6.8
#   AU-11   -- CIS 3.1, 3.4, 8.10
#   IA-2.1  -- CIS 6.3, 6.4, 6.5  (spreadsheet: IA-2(1))
# ============================================================

#run_test("AC-2")
run_test("AU-11")
# run_test("IA-2.1")
# run_test("SR-3")
# run_test("PE-12")