# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Import the SuccessFactors leave export (RCC_employees_leaves_data.xlsx): leave types and leave applications.

Approved leaves are submitted, pending ones stay open for the approver. Nobody has a leave allocation yet,
so the leave types allow a negative balance until HR enters entitlements. Attendance already on a leave day
is kept when the employee worked (Present, Work From Home, Half Day), and holidays inside a leave are left
alone, where HRMS would delete their attendance. Send the workbook batch by batch with scripts/leave_import.py.
"""

import re

import frappe
from frappe.utils import cint, flt, getdate
from hrms.hr.utils import get_holiday_dates_for_employee

# file leave type -> the type already on the site (the TAMS history uses these)
EXISTING = {
	"annual leave": "Annual Leave",
	"sick leave": "Sick Leave",
	"emergency leave": "Emergency Leave",
	"leave in lieu": "Lieu Leave",
	"special leave": "Special Leave",
	"leave without pay": "Leave Without Pay",
}
# file leave type -> the name it gets here
NAMES = {
	"accompany patient 15 days": "Accompany Patient 15 Days",
	"accompany patient 30 days": "Accompany Patient 30 Days",
	"compassionate leaves": "Compassionate Leave",
	"maternity": "Maternity Leave",
	"official duty": "Official Duty",
	"paternity": "Paternity Leave",
	"sick leave - paid 25%": "Sick Leave - Paid 25%",
	"sick leave - paid 35%": "Sick Leave - Paid 35%",
	"sick leave - paid 50%": "Sick Leave - Paid 50%",
	"sick leave - paid 75%": "Sick Leave - Paid 75%",
	"sick leave - unpaid": "Sick Leave - Unpaid",
	"special leave - maternity": "Special Leave - Maternity",
	"special leave - hajj": "Special Leave - Hajj",
	"special leave - marriage": "Special Leave - Marriage",
	"special leave - study": "Special Leave - Study",
	"accident leave (rcc)": "Accident Leave",
	"leave without pay rcc": "Leave Without Pay (RCC)",
	"official mission": "Official Mission",
}
UNPAID = {"Sick Leave - Unpaid", "Leave Without Pay (RCC)"}
WORKED = ("Present", "Work From Home", "Half Day")


def key(name):
	return re.sub(r"\s*-\s*", " - ", " ".join(str(name or "").split())).lower()


def leave_type_for(name):
	return EXISTING.get(key(name)) or NAMES.get(key(name))


@frappe.whitelist(methods=["POST"])
def import_leave_types(rows):
	"""rows: [sr_no, leave_type, code] from the "RCC Employee Leave Types" sheet"""
	frappe.only_for("System Manager")
	created, errors = [], []
	for _sr, name, code in frappe.parse_json(rows):
		leave_type = leave_type_for(name)
		if not leave_type:
			errors.append(f"{name}: unknown leave type")
			continue
		if not frappe.db.exists("Leave Type", leave_type):
			share = re.search(r"Paid (\d+)%", leave_type)
			frappe.get_doc(
				{
					"doctype": "Leave Type",
					"leave_type_name": leave_type,
					"is_lwp": 1 if leave_type in UNPAID else 0,
					"is_ppl": 1 if share else 0,
					"fraction_of_daily_salary_per_leave": cint(share.group(1)) / 100 if share else 0,
					"include_holiday": 1,
				}
			).insert(ignore_permissions=True)
			created.append(leave_type)
		values = {"custom_successfactors_code": str(code or "").strip().lstrip("(")}
		if not frappe.db.get_value("Leave Type", leave_type, "is_lwp"):
			# no allocations yet: leave taken shows as a negative balance until HR enters entitlements
			values["allow_negative"] = 1
		frappe.db.set_value("Leave Type", leave_type, values)
	return {"created": created, "errors": errors}


@frappe.whitelist(methods=["POST"])
def import_leaves(rows, dry_run=0):
	"""rows: [employee_no, first, last, department, leave_type, start, end, deduction_days, approval_status]

	A leave already imported (same employee, type and dates) is skipped, so a batch can be sent again.
	dry_run: check every row, then roll back.
	"""
	frappe.only_for("System Manager")
	employees = dict(
		frappe.get_all("Employee", {"employee_number": ("is", "set"), "status": "Active"}, ["employee_number", "name"], as_list=1)
	)
	result = {"created": 0, "submitted": 0, "skipped": 0, "errors": [], "kept_days": []}
	for emp_no, first, last, _dept, file_type, start, end, days, approval in frappe.parse_json(rows):
		label = f"{emp_no} {first} {last} {file_type} {start}..{end}"
		employee, leave_type = employees.get(str(emp_no)), leave_type_for(file_type)
		if not employee or not leave_type:
			result["errors"].append(f"{label}: {'no active employee with this number' if not employee else 'unknown leave type'}")
			continue
		if frappe.db.exists(
			"Leave Application",
			{"employee": employee, "leave_type": leave_type, "from_date": start, "to_date": end, "docstatus": ("!=", 2)},
		):
			result["skipped"] += 1
			continue
		approved = str(approval).strip().upper() == "APPROVED"
		leave = frappe.get_doc(
			{
				"doctype": "Leave Application",
				"employee": employee,
				"leave_type": leave_type,
				"from_date": start,
				"to_date": end,
				"posting_date": start,
				"status": "Approved" if approved else "Open",
				"follow_via_email": 0,
				"description": f"SuccessFactors: {flt(days):g} deduction day(s), {str(approval).strip().lower()}",
			}
		)
		# history: the leave stands even where the day already has attendance; mark_leave_days decides per day
		leave.validate_attendance = lambda: None
		leave.validate_leave_approver = lambda: None
		leave.update_attendance = lambda leave=leave: mark_leave_days(leave, result["kept_days"])
		kept = len(result["kept_days"])
		frappe.db.savepoint("leave_import")
		try:
			# no "insufficient balance" warnings, and no mails to approvers or employees for old leaves
			frappe.flags.mute_messages = frappe.flags.mute_emails = True
			leave.insert(ignore_permissions=True)
			result["created"] += 1
			if approved:
				leave.submit()
				result["submitted"] += 1
		except Exception as e:
			frappe.db.rollback(save_point="leave_import")
			del result["kept_days"][kept:]
			result["errors"].append(f"{label}: {frappe.utils.strip_html(str(e))[:300]}")
		finally:
			frappe.flags.mute_messages = frappe.flags.mute_emails = False
	if cint(dry_run):
		frappe.db.rollback()
	return result


def mark_leave_days(leave, kept_days):
	"""HRMS's update_attendance, except that worked days keep their attendance and holidays are left alone."""
	holidays = set()
	if not frappe.db.get_value("Leave Type", leave.leave_type, "include_holiday"):
		holidays = {getdate(d) for d in get_holiday_dates_for_employee(leave.employee, leave.from_date, leave.to_date)}
	day = getdate(leave.from_date)
	while day <= getdate(leave.to_date):
		if day not in holidays:
			attendance = frappe.db.get_value(
				"Attendance",
				{"employee": leave.employee, "attendance_date": day, "docstatus": ("!=", 2)},
				["name", "status", "working_hours"],
				as_dict=True,
			)
			if attendance and attendance.status in WORKED:
				kept_days.append(
					{"employee": leave.employee, "date": str(day), "status": attendance.status,
					 "hours": flt(attendance.working_hours, 2), "leave_type": leave.leave_type, "leave": leave.name}
				)
			else:
				leave.create_or_update_attendance(attendance.name if attendance else None, str(day))
		day = frappe.utils.add_days(day, 1)
