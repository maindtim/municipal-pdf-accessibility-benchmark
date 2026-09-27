#!/usr/bin/env python3
"""
Municipal Agenda Accessibility Benchmark - histogram builder.

Parses veraPDF (PDF/UA-1 validation profile) XML reports for a batch of
original (unremediated) municipal meeting agendas/minutes from U.S. local
governments, and produces:
  - results/summary.csv: one row per document (entity, passed/failed rules
    and checks, isCompliant).
  - results/rule_histogram.csv: one row per PDF/UA-1 rule clause, with how
    many of the measured documents failed that rule at least once, and the
    total number of individual checks that failed for that rule across all
    documents.

Input: a directory of veraPDF XML reports (one per source document), each
produced with:
    java -jar verapdf-cli.jar -f ua1 <document>.pdf

This script does not modify any PDF and does not certify legal compliance
with the ADA or any other law. It only reports what veraPDF's automated
PDF/UA-1 validation profile found in each source document, as published by
veraPDF (https://verapdf.org), an open-source tool maintained by the PDF
Association.

Usage:
    python build_histogram.py <input_dir_with_xml_reports> <output_dir>
"""
import csv
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _clean_xml_text(raw_text: str) -> str:
    """
    Some of the source reports were captured on Windows PowerShell with
    ``verapdf.bat ... > report.xml``, which on this host also interleaves
    PowerShell's own stderr (NativeCommandError noise, Java warning lines)
    into the redirected file. Every genuine line of veraPDF's XML output
    contains an angle bracket; every observed noise line does not. Stripping
    lines with no ``<`` recovers a well-formed document without altering any
    veraPDF-reported result.
    """
    return "\n".join(line for line in raw_text.splitlines() if "<" in line)


def parse_report(xml_path: Path):
    raw_text = xml_path.read_text(encoding="utf-8", errors="replace")
    root = ET.fromstring(_clean_xml_text(raw_text))
    vr = root.find(".//validationReport")
    if vr is None:
        return None
    details = vr.find("details")
    is_compliant = vr.get("isCompliant")
    passed_rules = int(details.get("passedRules", 0))
    failed_rules = int(details.get("failedRules", 0))
    passed_checks = int(details.get("passedChecks", 0))
    failed_checks = int(details.get("failedChecks", 0))

    rules = []
    for rule in details.findall("rule"):
        if rule.get("status") != "failed":
            continue
        clause = rule.get("clause")
        test_number = rule.get("testNumber")
        failed_checks_rule = int(rule.get("failedChecks", 0))
        desc_el = rule.find("description")
        description = desc_el.text.strip() if desc_el is not None and desc_el.text else ""
        rules.append(
            {
                "clause": clause,
                "testNumber": test_number,
                "failedChecks": failed_checks_rule,
                "description": description,
            }
        )

    return {
        "isCompliant": is_compliant,
        "passedRules": passed_rules,
        "failedRules": failed_rules,
        "passedChecks": passed_checks,
        "failedChecks": failed_checks,
        "rules": rules,
    }


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_dir> <output_dir>")
        sys.exit(1)

    input_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    xml_files = sorted(input_dir.glob("*.xml"))
    if not xml_files:
        print(f"No .xml files found in {input_dir}")
        sys.exit(1)

    summary_rows = []
    histogram = {}  # clause -> {"docs": set, "checks": int, "description": str}

    for xml_path in xml_files:
        entity = xml_path.stem
        try:
            parsed = parse_report(xml_path)
        except ET.ParseError as exc:
            print(f"WARNING: {xml_path} is not well-formed XML ({exc}), skipped")
            continue
        if parsed is None:
            print(f"WARNING: could not find a validationReport in {xml_path}, skipped")
            continue

        summary_rows.append(
            {
                "entity": entity,
                "isCompliant": parsed["isCompliant"],
                "passedRules": parsed["passedRules"],
                "failedRules": parsed["failedRules"],
                "passedChecks": parsed["passedChecks"],
                "failedChecks": parsed["failedChecks"],
            }
        )

        for rule in parsed["rules"]:
            clause = rule["clause"]
            entry = histogram.setdefault(
                clause, {"docs": set(), "checks": 0, "description": rule["description"]}
            )
            entry["docs"].add(entity)
            entry["checks"] += rule["failedChecks"]

    # summary.csv
    summary_path = output_dir / "summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "entity",
                "isCompliant",
                "passedRules",
                "failedRules",
                "passedChecks",
                "failedChecks",
            ],
        )
        writer.writeheader()
        writer.writerows(summary_rows)

    # rule_histogram.csv, sorted by number of documents affected (desc)
    histogram_path = output_dir / "rule_histogram.csv"
    with histogram_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["clause", "documents_affected", "total_failed_checks", "description"])
        for clause, entry in sorted(
            histogram.items(), key=lambda kv: (-len(kv[1]["docs"]), -kv[1]["checks"])
        ):
            writer.writerow([clause, len(entry["docs"]), entry["checks"], entry["description"]])

    total_docs = len(summary_rows)
    non_compliant = sum(1 for r in summary_rows if r["isCompliant"] == "false")
    print(f"Parsed {total_docs} documents ({input_dir}).")
    print(f"Non-compliant with PDF/UA-1: {non_compliant}/{total_docs}.")
    print(f"Wrote {summary_path} and {histogram_path}.")


if __name__ == "__main__":
    main()
