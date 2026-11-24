# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Set up a group company from the files it sends: company settings, holiday lists, OT policies,
shift types, branch, departments, designations and employees.

Pioneer Cement Industries came first (docs/Pioneer: Employees.xlsx and Shift Type.xlsx). Every step
skips or updates what is already there, so it can be sent again. Send it with
scripts/group_company_import.py.
"""

import datetime

import frappe
from frappe.utils import cint, cstr, flt, getdate, nowdate

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@frappe.whitelist(methods=["POST"])
def setup_company(company, country=None, currency=None, holiday_prefix=None, weekly_off=None, years=None,
				  branch=None, departments=None, ot_policies=None):
	"""Company settings and the masters the employees and shifts point to.

	country / currency: changed only while the company has no ledger entries; its accounts follow.
	holiday_prefix + weekly_off + years: "<prefix> <year>" lists with those days off, assigned to
	the company from 1 January (the company's earlier assignments are cancelled).
	ot_policies: [{policy_name, ...OT Policy fields}].
	"""
	frappe.only_for("System Manager")
	result = {"done": [], "errors": []}
	if not frappe.db.exists("Company", company):
		frappe.throw(frappe._("Company {0} not found").format(company))

	if country or currency:
		set_country_currency(company, country, currency, result)
	if holiday_prefix and weekly_off:
		set_holiday_lists(company, holiday_prefix, frappe.parse_json(weekly_off), frappe.parse_json(years or "[]"), result)
	if branch and not frappe.db.exists("Branch", branch):
		frappe.get_doc({"doctype": "Branch", "branch": branch}).insert()
		result["done"].append(f"branch {branch}")
	created = []
	for name in frappe.parse_json(departments or "[]"):
		ensure_department(name, company, created)
	result["done"] += [f"department {name}" for name in created]
	for policy in frappe.parse_json(ot_policies or "[]"):
		doc = frappe.get_doc("OT Policy", policy["policy_name"]) if frappe.db.exists("OT Policy", policy["policy_name"]) else frappe.new_doc("OT Policy")
		doc.update(policy)
		doc.save()
		result["done"].append(f"OT policy {doc.name}")
	return result


def set_country_currency(company, country, currency, result):
	doc = frappe.get_doc("Company", company)
	if (not country or doc.country == country) and (not currency or doc.default_currency == currency):
		return
	if frappe.db.exists("GL Entry", {"company": company}):
		result["errors"].append(f"{company} has ledger entries: country and currency left as they are")
		return
	if currency and doc.default_currency != currency:
		# accounts with no entries simply move to the new currency
		frappe.db.sql(
			"update `tabAccount` set account_currency=%s where company=%s and account_currency=%s",
			(currency, company, doc.default_currency),
		)
		frappe.db.set_value("Company", company, "default_currency", currency)
		result["done"].append(f"currency {currency}")
	if country and doc.country != country:
		frappe.db.set_value("Company", company, "country", country)
		result["done"].append(f"country {country}")


def make_holiday_lists(prefix, weekly_off, years, result):
	"""(year, name) of "<prefix> <year>" lists with those weekdays off; an empty weekly_off gives a list
	with no days off (for staff whose off days come from the roster)."""
	lists = []
	for year in years or [getdate().year]:
		name = f"{prefix} {year}"
		if not frappe.db.exists("Holiday List", name):
			doc = frappe.get_doc({
				"doctype": "Holiday List", "holiday_list_name": name,
				"from_date": f"{year}-01-01", "to_date": f"{year}-12-31", "holidays": [],
			})
			start = datetime.date(int(year), 1, 1)
			for n in range(366):
				day = start + datetime.timedelta(days=n)
				if day.year != int(year):
					break
				if WEEKDAYS[day.weekday()] in weekly_off:
					doc.append("holidays", {"holiday_date": day, "description": WEEKDAYS[day.weekday()], "weekly_off": 1})
			doc.insert()
			result["done"].append(f"holiday list {name}")
		lists.append((int(year), name))
	return lists


def set_holiday_lists(company, prefix, weekly_off, years, result):
	lists = make_holiday_lists(prefix, weekly_off, years, result)
	if lists:
		frappe.db.set_value("Company", company, "default_holiday_list", lists[0][1])
	if not frappe.db.exists("DocType", "Holiday List Assignment"):
		return  # HRMS before v16 reads the company's default list
	ours = {name for _, name in lists}
	for a in frappe.get_all(
		"Holiday List Assignment",
		{"applicable_for": "Company", "assigned_to": company, "docstatus": 1},
		["name", "holiday_list"],
	):
		if a.holiday_list not in ours:
			frappe.get_doc("Holiday List Assignment", a.name).cancel()
			result["done"].append(f"cancelled holiday assignment {a.name} ({a.holiday_list})")
	for year, name in lists:
		if not frappe.db.exists(
			"Holiday List Assignment", {"assigned_to": company, "holiday_list": name, "docstatus": 1}
		):
			frappe.get_doc({
				"doctype": "Holiday List Assignment", "applicable_for": "Company", "assigned_to": company,
				"holiday_list": name, "from_date": f"{year}-01-01",
			}).submit()
			result["done"].append(f"assigned {name}")


@frappe.whitelist(methods=["POST"])
def assign_employee_holiday_lists(employee_numbers, prefix, weekly_off=None, years=None):
	"""Give these employees their own "<prefix> <year>" lists (e.g. shift workers whose off days come
	from the roster), over the company's. HRMS 16 reads an Employee assignment, older HRMS the
	employee's Holiday List field."""
	frappe.only_for("System Manager")
	result = {"done": [], "errors": []}
	lists = make_holiday_lists(prefix, frappe.parse_json(weekly_off or "[]"), frappe.parse_json(years or "[]"), result)
	by_assignment = frappe.db.exists("DocType", "Holiday List Assignment")
	count = 0
	for number in frappe.parse_json(employee_numbers):
		employee = frappe.db.get_value("Employee", {"employee_number": cstr(number)})
		if not employee:
			result["errors"].append(f"{number}: not on the system")
			continue
		if not by_assignment:
			frappe.db.set_value("Employee", employee, "holiday_list", lists[0][1])
			count += 1
			continue
		for year, name in lists:
			if frappe.db.exists("Holiday List Assignment", {"assigned_to": employee, "holiday_list": name, "docstatus": 1}):
				continue
			frappe.get_doc({
				"doctype": "Holiday List Assignment", "applicable_for": "Employee", "assigned_to": employee,
				"holiday_list": name, "from_date": f"{year}-01-01",
			}).submit()
		count += 1
	result["done"].append(f"{count} employees on {prefix}")
	return result


@frappe.whitelist(methods=["POST"])
def import_shift_types(shifts):
	"""shifts: [{name, start_time, end_time, required_hours, ot_min_hours, ot_max_hours, ot_policy}]"""
	frappe.only_for("System Manager")
	result = {"created": [], "updated": [], "errors": []}
	for s in frappe.parse_json(shifts):
		values = {
			"start_time": s["start_time"],
			"end_time": s["end_time"],
			"custom_required_working_hours": flt(s.get("required_hours")),
			"custom_ot_min_hours": flt(s.get("ot_min_hours")),
			"custom_ot_max_hours": flt(s.get("ot_max_hours")),
			"ot_policy": s.get("ot_policy"),
			"begin_check_in_before_shift_start_time": cint(s.get("check_in_before")) or 60,
			# punches this long after the end still belong to the shift, so overtime counts
			"allow_check_out_after_shift_end_time": cint(s.get("check_out_after")) or 300,
			"working_hours_threshold_for_half_day": flt(s.get("half_day_below")),
			"working_hours_threshold_for_absent": flt(s.get("absent_below")),
		}
		if s.get("undertime_tolerance") is not None:
			values["flexi_undertime_tolerance"] = cint(s["undertime_tolerance"])
		if frappe.db.exists("Shift Type", s["name"]):
			doc = frappe.get_doc("Shift Type", s["name"])
			doc.update(values)
			doc.save()
			result["updated"].append(s["name"])
			continue
		frappe.get_doc({
			"doctype": "Shift Type",
			"__newname": s["name"],
			"enable_auto_attendance": 1,
			"process_attendance_after": nowdate(),
			"determine_check_in_and_check_out": "Alternating entries as IN and OUT during the same shift",
			"working_hours_calculation_based_on": "First Check-in and Last Check-out",
			**values,
		}).insert()
		result["created"].append(s["name"])
	return result


@frappe.whitelist(methods=["POST"])
def import_employees(rows, company, branch=None, shifts=None, move=None):
	"""rows: {name, employee_number, first_name, last_name, date_of_joining, department, designation,
	company_email, default_shift}. name is the employee ID the company uses (e.g. HR-EMP-50002).
	shifts maps the file's shift name to the Shift Type. Existing employees (same number) are updated."""
	frappe.only_for("System Manager")
	shifts = frappe.parse_json(shifts or "{}")
	move = {cstr(n) for n in frappe.parse_json(move or "[]")}  # employee numbers to bring over from another company
	result = {"created": 0, "updated": 0, "errors": []}
	for r in frappe.parse_json(rows):
		number = cstr(r["employee_number"]).strip()
		existing = frappe.db.get_value("Employee", {"employee_number": number}) or (
			r.get("name") if r.get("name") and frappe.db.exists("Employee", r["name"]) else None
		)
		employee = frappe.get_doc("Employee", existing) if existing else frappe.new_doc("Employee")
		moved_from = None
		if existing and employee.company != company:
			if number not in move:
				result["errors"].append(f"{number}: already used by {existing} in {employee.company}")
				continue
			moved_from = employee.company
		if r.get("employee_name"):  # one full name: first, middle and last word(s)
			words = cstr(r["employee_name"]).split()
			r["first_name"], r["middle_name"], r["last_name"] = (
				(words[0], " ".join(words[1:-1]), words[-1]) if len(words) > 1 else (words[0], "", "")
			)
		employee.update({
			"first_name": cstr(r.get("first_name")).strip(),
			"middle_name": cstr(r.get("middle_name")).strip() if "middle_name" in r else employee.middle_name,
			"last_name": cstr(r.get("last_name")).strip(),
			"company": company,
			"status": r.get("status") or (employee.status if existing else "Active"),
			"custom_id_card_no": cstr(r.get("id_card_no")).strip() or employee.get("custom_id_card_no"),
			"date_of_joining": r.get("date_of_joining") or employee.date_of_joining,
			"department": ensure_department(r.get("department"), company),
			"designation": ensure_designation(r.get("designation")),
			"branch": branch or employee.branch,
			"company_email": cstr(r.get("company_email")).strip().lower() or employee.company_email,
			"default_shift": shifts.get(cstr(r.get("default_shift")).strip()) or employee.default_shift,
		})
		for field in ("gender", "date_of_birth", "cell_number"):
			if r.get(field):
				employee.set(field, r[field])
		if employee.gender and not frappe.db.exists("Gender", employee.gender):
			employee.gender = None
		if not existing:
			employee.employee_number = number
			if not frappe.db.exists("Employee", {"attendance_device_id": number}):
				employee.attendance_device_id = number  # the clock card is the employee number
		# the file has no date of birth or gender; HR fills both in later
		employee.flags.ignore_mandatory = True
		frappe.db.savepoint("group_employee")
		try:
			if existing:
				employee.save()
			else:
				employee.insert(set_name=r.get("name") or None)
		except Exception as e:
			frappe.db.rollback(save_point="group_employee")
			result["errors"].append(f"{number}: {frappe.utils.strip_html(str(e))[:200]}")
			continue
		if moved_from:
			# their attendance history goes with them
			frappe.db.sql(
				"update `tabAttendance` set company=%s, department=%s where employee=%s and company=%s",
				(company, employee.department, employee.name, moved_from),
			)
			result.setdefault("moved", []).append(f"{number} {employee.employee_name} from {moved_from}")
		result["updated" if existing else "created"] += 1
	return result


@frappe.whitelist(methods=["POST"])
def set_reports_to(pairs):
	"""pairs: [[employee_number, manager_employee_number]], once everyone is in."""
	frappe.only_for("System Manager")
	numbers = dict(frappe.get_all("Employee", {"employee_number": ("is", "set")}, ["employee_number", "name"], as_list=1))
	result = {"updated": 0, "missing": []}
	for number, manager in frappe.parse_json(pairs):
		employee, boss = numbers.get(cstr(number)), numbers.get(cstr(manager))
		if not employee:
			continue
		if not boss:
			result["missing"].append(f"{number}: manager {manager} is not on the system")
			continue
		if frappe.db.get_value("Employee", employee, "reports_to") != boss and employee != boss:
			frappe.db.set_value("Employee", employee, "reports_to", boss)
			result["updated"] += 1
	return result


def ensure_department(name, company, created=None):
	name = " ".join(cstr(name).split())
	if not name:
		return None
	existing = frappe.db.get_value("Department", {"department_name": name, "company": company})
	if existing:
		return existing
	root = frappe.db.get_value("Department", {"parent_department": ("is", "not set"), "is_group": 1}) or None
	doc = frappe.get_doc({"doctype": "Department", "department_name": name, "company": company, "parent_department": root}).insert()
	if created is not None:
		created.append(doc.name)
	return doc.name


def ensure_designation(title):
	title = " ".join(cstr(title).split())
	if not title:
		return None
	return frappe.db.exists("Designation", title) or frappe.get_doc({"doctype": "Designation", "designation_name": title}).insert().name
