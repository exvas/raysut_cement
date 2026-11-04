"""Send the SuccessFactors leave export (RCC_employees_leaves_data.xlsx) to a site over the REST API.

	RC_TOKEN=api_key:api_secret python3 scripts/leave_import.py https://site LEAVES.xlsx [--dry-run]
		[--kept-days KEPT.csv] [--not-imported ERRORS.csv]

First the leave types ("RCC Employee Leave Types"), then the leaves ("Rcc Employees leave Data"), 20 at a
time. --dry-run creates the leave types, then checks every leave and rolls it back. --kept-days writes
the leave days that kept their attendance because the employee worked, --not-imported the leaves that
could not go in (both for HR to review). The token's user needs System Manager; a leave already
imported is skipped, so an interrupted run can simply be started again.
"""

import argparse
import csv
import datetime

from tams_import import batches, call


def iso(value):
	return value.date().isoformat() if isinstance(value, datetime.datetime) else str(value).strip()


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("site")
	parser.add_argument("workbook")
	parser.add_argument("--dry-run", action="store_true")
	parser.add_argument("--kept-days", metavar="CSV")
	parser.add_argument("--not-imported", metavar="CSV")
	args = parser.parse_args()

	from openpyxl import load_workbook

	book = load_workbook(args.workbook, read_only=True, data_only=True)
	types = [list(r[:3]) for r in list(book["RCC Employee Leave Types"].iter_rows(values_only=True))[1:] if r[1]]
	leaves = [
		[r[0], r[1], r[2], r[3], str(r[4]).strip(), iso(r[5]), iso(r[6]), r[7], r[8]]
		for r in list(book["Rcc Employees leave Data"].iter_rows(values_only=True))[1:]
		if r[0] is not None
	]

	# the leave types go in even on a dry run: the leaves are checked against them (sending them again changes nothing)
	result = call(args.site, "leave_import.import_leave_types", rows=types)
	print(f"leave types: {len(types)} read, created {result['created']}")
	for error in result["errors"]:
		print("  error:", error)

	totals, kept, errors = {"created": 0, "submitted": 0, "skipped": 0, "errors": 0}, [], []
	for i, batch in enumerate(batches(leaves, 20)):
		result = call(args.site, "leave_import.import_leaves", rows=batch, dry_run=int(args.dry_run))
		for name in ("created", "submitted", "skipped"):
			totals[name] += result[name]
		totals["errors"] += len(result["errors"])
		kept += result["kept_days"]
		errors += result["errors"]
		for error in result["errors"]:
			print("  error:", error)
		print(f"leaves {min((i + 1) * 20, len(leaves))}/{len(leaves)}: {totals}, {len(kept)} worked days kept", flush=True)

	if args.kept_days and kept:
		with open(args.kept_days, "w", newline="") as f:
			writer = csv.DictWriter(f, fieldnames=list(kept[0]))
			writer.writeheader()
			writer.writerows(kept)
		print("worked days kept on a leave:", args.kept_days)
	if args.not_imported and errors:
		with open(args.not_imported, "w", newline="") as f:
			writer = csv.writer(f)
			writer.writerow(["leave", "reason"])
			writer.writerows(error.split(": ", 1) for error in errors)
		print("leaves not imported:", args.not_imported)


if __name__ == "__main__":
	main()
