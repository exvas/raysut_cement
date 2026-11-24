"""Set up a group company on a site from the files it sent, over the REST API.

	RC_TOKEN=api_key:api_secret python3 scripts/group_company_import.py SITE PROFILE FOLDER [--company NAME]

PROFILE is pioneer or sohar; FOLDER holds that profile's employee and shift workbooks (see PROFILES).
In order: company settings (country, currency, holiday lists, branch, departments, OT policies), shift
types, employees (25 at a time), staff on their own holiday list, then who reports to whom. Every step
skips or updates what is already there, so it can be run again. The token's user needs System Manager.
"""

import argparse
import datetime
import os
import re

from tams_import import batches, call

PROFILES = {
	"pioneer": {
		"company": "Pioneer Cement Industries",
		"employee_file": "Employees.xlsx",
		"shift_file": "Shift Type.xlsx",
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
		# shifts allowing at most this much OT take the second policy
		"second_policy_up_to": 3,
		# a shift's name in the file -> its name here (the file's "Shift A" etc. would clash with Raysut's)
		"shift_names": {"Shift A - Housekeeping, Office Boy & Canteen": "Shift A (Housekeeping, Office Boy, Canteen)"},
		# the employee file's Default Shift -> the shift in the shift file; anything else gets no default
		"employee_shifts": {"General Shift": "General"},
		# the Series column is the employee ID Pioneer uses (HR-EMP-50002)
		"series_is_id": True,
	},
	"sohar": {
		"company": "Sohar Cement Factory",
		"employee_file": "SCF Employee updated.xlsx",
		"shift_file": "SCF Shift Type.xlsx",
		"holiday_prefix": "Sohar Cement",
		"weekly_off": ["Friday", "Saturday"],
		"years": [2026, 2027],
		# the "Shift Roaster" holiday group: no weekly off, the roster sets their off days
		"roster_holidays": {"group": "shift roaster", "prefix": "Sohar Shift Roster"},
		"branch": "Sohar",
		"shift_prefix": "SCF - ",
		"ot_policies": [
			{"policy_name": "Sohar Standard OT", "min_ot_minutes": 60, "max_ot1_hours": 4, "ot1_rate": 1.25,
			 "ot2_on_holidays": 1, "max_ot2_hours": 12, "ot2_rate": 2,
			 "description": "Sohar: OT after 8 hours, from 1 hour, up to 4 a day at 1.25 (night OT 21:00-05:00 is 1.5); off days and holidays as OT2 at 2, up to 12 hours."},
		],
		# rotating staff (A,B,C / D,E) get no default; HR rosters them with the Shift Assignment Tool
		"employee_shifts": {"Genral": "G1", "General": "G1", "Shift A": "A", "Shift E": "E"},
		# Raysut records from the TAMS import that are really Sohar staff: moved over with their attendance
		"move": ["300077", "300086"],
		# managers named in the file who are not Sohar staff (or are misspelt): their employee number
		"managers": {"Yaqoob Al Balushi": "1159", "Amitvikram Pandey": "300121", "Suad Em Maqbali": "300032"},
	},
}


def hhmm(value):
	return value.strftime("%H:%M:%S") if isinstance(value, datetime.time) else str(value)


def as_date(value):
	"""datetime, or d.m.yyyy text as Sohar writes it"""
	if isinstance(value, datetime.datetime):
		return value.date().isoformat()
	m = re.match(r"^\s*(\d{1,2})[./-](\d{1,2})[./-](\d{4})\s*$", str(value or ""))
	return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def words(value):
	return " ".join(str(value or "").split())


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

	shift_book = load_workbook(os.path.join(args.folder, p["shift_file"]), read_only=True, data_only=True)
	shift_rows = [r for r in list(shift_book["Shift Type"].iter_rows(values_only=True))[1:] if r[0] and r[1]]
	sheet = load_workbook(os.path.join(args.folder, p["employee_file"]), read_only=True, data_only=True).worksheets[0]
	header, *rows = [r for r in sheet.iter_rows(values_only=True) if any(v not in (None, "") for v in r)]
	col = {words(h): i for i, h in enumerate(header)}
	rows = [r for r in rows if r[col["Employee Number"]]]

	def text(r, name):
		value = r[col[name]] if name in col and col[name] < len(r) else None
		if isinstance(value, float) and value.is_integer():
			value = int(value)
		return words(value)

	departments = sorted({text(r, "Department") for r in rows if text(r, "Department")})
	print("company:", call(args.site, "group_company.setup_company", company=company, country=p.get("country"),
		currency=p.get("currency"), holiday_prefix=p["holiday_prefix"], weekly_off=p["weekly_off"], years=p["years"],
		branch=p["branch"], departments=departments, ot_policies=p["ot_policies"]))

	shifts, shift_map = [], {}
	for r in shift_rows:
		name = p["shift_prefix"] + p.get("shift_names", {}).get(words(r[0]), words(r[0]))
		shift_map[words(r[0])] = name
		policies = p["ot_policies"]
		second = p.get("second_policy_up_to")
		shifts.append({
			"name": name, "start_time": hhmm(r[1]), "end_time": hhmm(r[2]),
			"check_in_before": r[4], "check_out_after": r[5],
			"half_day_below": r[6] if isinstance(r[6], (int, float)) else 0,
			"required_hours": float(r[7] or 0), "ot_min_hours": r[8], "ot_max_hours": r[9],
			"absent_below": r[11] if isinstance(r[11], (int, float)) else 0,
			"undertime_tolerance": r[12] if isinstance(r[12], (int, float)) else None,
			"ot_policy": policies[1 if second and float(r[9] or 0) <= second else 0]["policy_name"],
		})
	print("shift types:", call(args.site, "group_company.import_shift_types", shifts=shifts))
	employee_shifts = {k: shift_map[v] for k, v in p["employee_shifts"].items()}

	people = []
	for r in rows:
		person = {
			"employee_number": text(r, "Employee Number"),
			"first_name": text(r, "First Name"),
			"last_name": text(r, "Last Name"),
			"date_of_joining": as_date(r[col["Date of Joining"]]) or "",
			"department": text(r, "Department"),
			"designation": text(r, "Designation"),
			"company_email": text(r, "Company Email"),
			"default_shift": text(r, "Default Shift"),
		}
		if p.get("series_is_id"):
			person["name"] = text(r, "Series")
		middle = text(r, "Middle Name")
		if middle or "Middle Name" in col:
			# Sohar sometimes repeats the last name as the middle name
			person["middle_name"] = "" if middle.lower() == person["last_name"].lower() else middle
		for key, column in (("gender", "Gender"), ("cell_number", "Mobile"), ("status", "Status")):
			if text(r, column):
				person[key] = text(r, column).title() if key != "cell_number" else text(r, column)
		if as_date(r[col["Date of Birth"]]):
			person["date_of_birth"] = as_date(r[col["Date of Birth"]])
		people.append(person)

	totals = {"created": 0, "updated": 0}
	for i, batch in enumerate(batches(people, 25)):
		result = call(args.site, "group_company.import_employees", rows=batch, company=company, branch=p["branch"],
					  shifts=employee_shifts, move=p.get("move", []))
		for k in totals:
			totals[k] += result[k]
		for error in result["errors"]:
			print("  error:", error)
		for moved in result.get("moved", []):
			print("  moved:", moved)
		print(f"employees {min((i + 1) * 25, len(people))}/{len(people)}: {totals}", flush=True)

	roster = p.get("roster_holidays")
	if roster:
		numbers = [text(r, "Employee Number") for r in rows if text(r, "Holiday List").lower() == roster["group"]]
		print("roster holidays:", call(args.site, "group_company.assign_employee_holiday_lists",
			employee_numbers=numbers, prefix=roster["prefix"], weekly_off=[], years=p["years"]))

	# Reports to: an employee number, or a name to find among this file's people
	full_names = {
		text(r, "Employee Number"): " ".join(filter(None, [text(r, "First Name"), text(r, "Middle Name"), text(r, "Last Name")])).lower()
		for r in rows
	}

	def manager_number(value):
		value = words(value)
		if value in p.get("managers", {}):
			return p["managers"][value]
		if value.isdigit():
			return value
		hits = [n for n, full in full_names.items() if all(w.lower() in full.split() for w in value.split())]
		return hits[0] if len(hits) == 1 else value

	pairs = [[text(r, "Employee Number"), manager_number(text(r, "Reports to"))] for r in rows if text(r, "Reports to")]
	print("reports to:", call(args.site, "group_company.set_reports_to", pairs=pairs))
	no_shift = [x["employee_number"] for x in people if x["default_shift"] not in employee_shifts]
	print(f"{len(no_shift)} employees have no default shift yet (assign them with the Shift Assignment Tool)")


if __name__ == "__main__":
	main()
