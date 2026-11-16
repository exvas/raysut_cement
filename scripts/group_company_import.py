"""Set up a group company on a site from the files it sent, over the REST API.

	RC_TOKEN=api_key:api_secret python3 scripts/group_company_import.py SITE pioneer FOLDER [--company NAME]

FOLDER holds Employees.xlsx and "Shift Type.xlsx" (docs/Pioneer). In order: company settings (country,
currency, holiday lists, branch, departments, OT policies), shift types, employees (25 at a time),
then who reports to whom. Every step skips or updates what is already there, so it can be run again.
The token's user needs System Manager.
"""

import argparse
import datetime
import os

from tams_import import batches, call

# one entry per group company; the files' own names map onto these
PROFILES = {
	"pioneer": {
		"company": "Pioneer Cement Industries",
		"country": "United Arab Emirates",
		"currency": "AED",
		"holiday_prefix": "Pioneer Cement",
		"weekly_off": ["Saturday", "Sunday"],
		"years": [2026, 2027],
		"branch": "Ras Al Khaimah",
		"shift_prefix": "PCI - ",
		# Shift Type.xlsx: OT from 1 hour, 4 a day (3 for security, housekeeping), holiday OT up to 12
		"ot_policies": [
			{"policy_name": "Pioneer Standard OT", "min_ot_minutes": 60, "max_ot1_hours": 4, "ot1_rate": 1.25,
			 "ot2_on_holidays": 1, "max_ot2_hours": 12, "ot2_rate": 1.5,
			 "description": "Pioneer: OT from 1 hour, up to 4 hours a day at 1.25; off days and holidays as OT2 at 1.5, up to 12 hours."},
			{"policy_name": "Pioneer Security OT", "min_ot_minutes": 60, "max_ot1_hours": 3, "ot1_rate": 1.25,
			 "ot2_on_holidays": 1, "max_ot2_hours": 12, "ot2_rate": 1.5,
			 "description": "Pioneer 9-hour shifts (security, housekeeping): OT from 1 hour, up to 3 hours a day at 1.25; holidays as OT2 at 1.5."},
		],
		# a shift's name in the file -> its name here (the file's "Shift A" etc. would clash with Raysut's)
		"shift_names": {"Shift A - Housekeeping, Office Boy & Canteen": "Shift A (Housekeeping, Office Boy, Canteen)"},
		# the employee file's Default Shift -> the shift in the shift file
		"employee_shifts": {"General Shift": "General"},
	},
}


def hhmm(value):
	return value.strftime("%H:%M:%S") if isinstance(value, datetime.time) else str(value)


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("site")
	parser.add_argument("profile", choices=list(PROFILES))
	parser.add_argument("folder")
	parser.add_argument("--company", help="the company's name on the site, if not the profile's")
	args = parser.parse_args()
	p = PROFILES[args.profile]
	company = args.company or p["company"]

	from openpyxl import load_workbook

	shift_book = load_workbook(os.path.join(args.folder, "Shift Type.xlsx"), read_only=True, data_only=True)
	shift_rows = [r for r in list(shift_book["Shift Type"].iter_rows(values_only=True))[1:] if r[0] and r[1]]
	employee_book = load_workbook(os.path.join(args.folder, "Employees.xlsx"), read_only=True, data_only=True)
	sheet = employee_book.worksheets[0]
	header, *rows = list(sheet.iter_rows(values_only=True))
	col = {h: i for i, h in enumerate(header)}
	rows = [r for r in rows if r[col["Employee Number"]]]

	departments = sorted({str(r[col["Department"]]).strip() for r in rows if r[col["Department"]]})
	print("company:", call(args.site, "group_company.setup_company", company=company, country=p["country"],
		currency=p["currency"], holiday_prefix=p["holiday_prefix"], weekly_off=p["weekly_off"], years=p["years"],
		branch=p["branch"], departments=departments, ot_policies=p["ot_policies"]))

	shifts, shift_map = [], {}
	for r in shift_rows:
		name = p["shift_prefix"] + p["shift_names"].get(r[0].strip(), r[0].strip())
		shift_map[r[0].strip()] = name
		required = float(r[7] or 0)
		shifts.append({
			"name": name, "start_time": hhmm(r[1]), "end_time": hhmm(r[2]), "required_hours": required,
			"ot_min_hours": r[8], "ot_max_hours": r[9],
			"ot_policy": p["ot_policies"][1 if float(r[9] or 0) <= 3 else 0]["policy_name"],
		})
	print("shift types:", call(args.site, "group_company.import_shift_types", shifts=shifts))
	employee_shifts = {k: shift_map[v] for k, v in p["employee_shifts"].items()}

	def text(r, name):
		value = r[col[name]]
		return "" if value is None else str(value).strip()

	people = [{
		"name": text(r, "Series"),
		"employee_number": text(r, "Employee Number"),
		"first_name": text(r, "First Name"),
		"last_name": text(r, "Last Name"),
		"date_of_joining": r[col["Date of Joining"]].date().isoformat() if isinstance(r[col["Date of Joining"]], datetime.datetime) else text(r, "Date of Joining"),
		"department": text(r, "Department"),
		"designation": text(r, "Designation"),
		"company_email": text(r, "Company Email"),
		"default_shift": text(r, "Default Shift"),
	} for r in rows]
	totals = {"created": 0, "updated": 0}
	for i, batch in enumerate(batches(people, 25)):
		result = call(args.site, "group_company.import_employees", rows=batch, company=company, branch=p["branch"], shifts=employee_shifts)
		for k in totals:
			totals[k] += result[k]
		for error in result["errors"]:
			print("  error:", error)
		print(f"employees {min((i + 1) * 25, len(people))}/{len(people)}: {totals}", flush=True)

	pairs = [[text(r, "Employee Number"), text(r, "Reports to")] for r in rows if text(r, "Reports to")]
	print("reports to:", call(args.site, "group_company.set_reports_to", pairs=pairs))
	no_shift = [p_["employee_number"] for p_ in people if not p_["default_shift"]]
	print(f"{len(no_shift)} employees have no default shift yet (attendance is not marked for them until they get one)")


if __name__ == "__main__":
	main()
