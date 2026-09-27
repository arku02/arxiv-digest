"""Run explicit unittest files and emit machine-readable, fail-closed evidence."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys
import unittest


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.passed_cases = []
        self.passed_ids = set()

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed_cases.append(test.id())
        match = re.match(r"test_([RD]\d+)_", getattr(test, "_testMethodName", ""))
        if match:
            self.passed_ids.add(match.group(1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    sys.path.insert(0, str(root))
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for index, name in enumerate(args.files):
        file = (root / name).resolve()
        if not file.is_relative_to(root):
            raise ValueError("Test file escapes project")
        spec = importlib.util.spec_from_file_location(f"workflow_test_{index}", file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        suite.addTests(loader.loadTestsFromModule(module))
    result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
    report = {
        "token": args.token, "python": sys.version, "tests": result.testsRun,
        "passed": len(result.passed_cases), "passedIds": sorted(result.passed_ids),
        "passedCases": result.passed_cases, "failures": len(result.failures),
        "errors": len(result.errors), "skipped": len(result.skipped),
        "expectedFailures": len(result.expectedFailures),
        "unexpectedSuccesses": len(result.unexpectedSuccesses),
        "success": result.wasSuccessful(),
    }
    target = Path(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
