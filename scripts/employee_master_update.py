"""Apply HR's employee master (Raysut_masterdata.xlsx, sheet "Employee List") to a site over the REST API.

	RC_TOKEN=api_key:api_secret python3 scripts/employee_master_update.py SITE WORKBOOK [--company NAME] [--keep-status]

Columns: Employee name, Punching ID, Employee ID, Civil ID number, Civil ID expiry date, Passport
number, Passport expiry date, Designation, Department, Location, Joining date, Reporting person,
Shift / roster group. Employees are matched on Employee ID (employee_number); the master's name,
designation, department, joining date and Civil ID (into ID Card No.) replace what the site has,
everyone in it is set Active (unless --keep-status), new IDs are added, then reports-to is set.
Employees not in the master are left alone. Safe to run again.
"""

import argparse
import datetime

from tams_import import batches, call

# the master's shift / roster group -> Shift Type; a blank keeps the employee's current shift
SHIFTS = {"General shift": "Fixed 07:30-15:00"}


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("site")
	parser.add_argument("workbook")
	parser.add_argument("--company", default="Raysut Cement Company SAOG")
	parser.add_argument("--keep-status", action="store_true", help="don't set everyone in the master Active")
	args = parser.parse_args()

	from openpyxl import load_workbook

	sheet = load_workbook(args.workbook, read_only=True, data_only=True).worksheets[0]
	header, *rows = [r for r in sheet.iter_rows(values_only=True) if any(v not in (None, "") for v in r)]
	col = {str(h).strip(): i for i, h in enumerate(header)}

	def text(r, name):
		value = r[col[name]] if col.get(name) is not None and col[name] < len(r) else None
		if isinstance(value, datetime.datetime):
			return value.date().isoformat()
		if isinstance(value, float) and value.is_integer():
			value = int(value)
		return "" if value is None else " ".join(str(value).split())

	people = []
	for r in rows:
		number = text(r, "Employee ID")
		if not number:
			continue
		person = {
			"employee_number": number,
			"employee_name": text(r, "Employee name"),
			"designation": text(r, "Designation"),
			"department": text(r, "Department"),
			"date_of_joining": text(r, "Joining date"),
			"id_card_no": text(r, "Civil ID number"),
			"default_shift": text(r, "Shift / roster group"),
		}
		if not args.keep_status:
			person["status"] = "Active"
		people.append(person)

	totals = {"created": 0, "updated": 0}
	for i, batch in enumerate(batches(people, 25)):
		result = call(args.site, "group_company.import_employees", rows=batch, company=args.company, shifts=SHIFTS)
		for k in totals:
			totals[k] += result[k]
		for error in result["errors"]:
			print("  error:", error)
		print(f"employees {min((i + 1) * 25, len(people))}/{len(people)}: {totals}", flush=True)

	pairs = [[text(r, "Employee ID"), text(r, "Reporting person (name & ID)")] for r in rows
			 if text(r, "Employee ID") and text(r, "Reporting person (name & ID)")]
	print("reports to:", call(args.site, "group_company.set_reports_to", pairs=pairs))


if __name__ == "__main__":
	main()
