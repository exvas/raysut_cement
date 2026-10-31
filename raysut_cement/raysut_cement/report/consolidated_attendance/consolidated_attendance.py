# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Consolidated Monthly Attendance: per employee, every day of the period counted once.

Each day is: not employed (before joining / after relieving), else the Attendance's status (PR, AB,
a leave column; Half Day = 0.5 PR + 0.5 of its leave, else 0.5 AB), else the holiday list's
weekly off (WO) or public holiday (HL), else not marked (NM). So per row
PR + AB + WO + HL + NM + leaves + Days Not Employed = days in the period; a row that does not add
up (two attendances on one day) is flagged. Late, under time, OT1, OT2 and worked hours are sums
of what attendance processing stored on each Attendance.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.utils import add_days, cint, date_diff, flt, getdate
from frappe.utils.nestedset import get_descendants_of

WORKED = ("Present", "Work From Home")
DURATIONS = (  # fieldname, label, source total
	("late", "Late (HH:MM)", "late_minutes"),
	("under_time", "Under Time (HH:MM)", "under_time_minutes"),
	("ot1", "OT1 (HH:MM)", "ot1_minutes"),
	("ot2", "OT2 (HH:MM)", "ot2_minutes"),
	("worked", "Total Worked Hr (HH:MM)", "worked_minutes"),
)
DAY_COUNTS = ("pr", "ab", "wo", "hl", "nm")
UNSPECIFIED_LEAVE = "LV"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date must be before To Date"))

	leave_codes = get_leave_codes()
	employees = get_employees(filters)
	rows = build_rows(filters, employees, leave_codes)
	used = {code for row in rows for code in leave_codes.values() if row.get(leave_field(code))}
	if any(row.get(leave_field(UNSPECIFIED_LEAVE)) for row in rows):
		used.add(UNSPECIFIED_LEAVE)
	shown = sorted(set(leave_codes.values()) | {UNSPECIFIED_LEAVE}) if cint(filters.show_zero_leave_columns) else sorted(used)
	return get_columns(shown), group_rows(rows, filters, shown)


# ---------------------------------------------------------------- inputs


def leave_field(code):
	return "leave_" + frappe.scrub(code)


def get_leave_codes():
	"""Leave Type -> its Report Abbreviation, else its initials (Annual Leave -> AL)."""
	codes = {}
	for leave_type in frappe.get_all("Leave Type", fields=["name", "report_abbreviation"]):
		codes[leave_type.name] = (leave_type.report_abbreviation or "").strip().upper() or "".join(
			word[0] for word in leave_type.name.split() if word
		).upper()
	return codes


def get_employees(filters):
	"""Through get_list, so the user's permissions (branch, department, ...) decide who is listed."""
	conditions = {"company": filters.company}
	if filters.status and filters.status != "All":
		conditions["status"] = filters.status
	for field in ("employee", "branch", "employment_type"):
		if filters.get(field):
			conditions["name" if field == "employee" else field] = filters.get(field)
	conditions = [["Employee", field, "=", value] for field, value in conditions.items()]
	if filters.department:
		conditions.append(
			["Employee", "department", "in", [filters.department, *get_descendants_of("Department", filters.department)]]
		)
	conditions += strict_user_permissions()
	employees = frappe.get_list(
		"Employee",
		filters=conditions,
		fields=["name", "employee_name", "department", "designation", "branch", "date_of_joining", "relieving_date",
				"holiday_list", "default_shift"],
		order_by="name",
		limit_page_length=0,
	)
	if filters.shift_type:
		on_shift = set(
			frappe.get_all(
				"Attendance",
				filters={"shift": filters.shift_type, "docstatus": 1, "attendance_date": ("between", [filters.from_date, filters.to_date])},
				pluck="employee",
				distinct=True,
			)
		)
		employees = [e for e in employees if e.default_shift == filters.shift_type or e.name in on_shift]
	return employees


def strict_user_permissions():
	"""A user limited to some branches or departments sees only employees in them.

	Frappe's own check lets through employees with no branch / department at all, unless the site
	has strict user permissions on; for attendance totals that would show nearly everyone.
	"""
	from frappe.core.doctype.user_permission.user_permission import get_user_permissions

	permissions = get_user_permissions(frappe.session.user)
	conditions = []
	for doctype, field in (("Branch", "branch"), ("Department", "department")):
		allowed = [p.get("doc") for p in permissions.get(doctype, []) if p.get("applicable_for") in (None, "", "Employee")]
		if allowed:
			conditions.append(["Employee", field, "in", allowed])
	return conditions


def get_attendance(filters, employee_names):
	if not employee_names:
		return []
	attendance = DocType("Attendance")
	return (
		frappe.qb.from_(attendance)
		.select(
			attendance.employee, attendance.attendance_date, attendance.status, attendance.leave_type,
			attendance.late_entry, attendance.late_minutes, attendance.under_time_minutes,
			attendance.custom_ot1_hours, attendance.custom_ot2_hours, attendance.working_hours,
		)
		.where(
			(attendance.docstatus == 1)
			& (attendance.attendance_date[filters.from_date : filters.to_date])
			& (attendance.employee.isin(employee_names))
		)
		.run(as_dict=True)
	)


def get_holidays(employees, filters):
	"""{holiday list: {date: weekly_off}} for the lists these employees follow."""
	company_list = frappe.get_cached_value("Company", filters.company, "default_holiday_list")
	lists = {e.holiday_list or company_list for e in employees} - {None}
	holidays = defaultdict(dict)
	if lists:
		for h in frappe.get_all(
			"Holiday",
			filters={"parent": ("in", list(lists)), "holiday_date": ("between", [filters.from_date, filters.to_date])},
			fields=["parent", "holiday_date", "weekly_off"],
		):
			holidays[h.parent][h.holiday_date] = cint(h.weekly_off)
	return holidays, company_list


# ---------------------------------------------------------------- rows


def build_rows(filters, employees, leave_codes):
	from_date, to_date = getdate(filters.from_date), getdate(filters.to_date)
	days = [add_days(from_date, i) for i in range(date_diff(to_date, from_date) + 1)]
	by_day = defaultdict(list)
	for a in get_attendance(filters, [e.name for e in employees]):
		by_day[(a.employee, a.attendance_date)].append(a)
	holidays, company_list = get_holidays(employees, filters)

	rows = []
	for e in employees:
		row = frappe._dict(
			employee=e.name,
			employee_name=e.employee_name,
			department=e.department or _("Not Set"),
			designation=e.designation,
			branch=e.branch or _("Not Set"),
			late_count=0,
			days_not_employed=0,
			**dict.fromkeys(DAY_COUNTS, 0.0),
			**{total: 0.0 for _f, _l, total in DURATIONS},
		)
		holiday_dates = holidays.get(e.holiday_list or company_list, {})
		joining, relieving = getdate(e.date_of_joining) if e.date_of_joining else None, getdate(e.relieving_date) if e.relieving_date else None
		for day in days:
			if (joining and day < joining) or (relieving and day > relieving):
				row.days_not_employed += 1
			elif by_day.get((e.name, day)):
				for a in by_day[(e.name, day)]:
					count_attendance(row, a, leave_codes)
			elif day in holiday_dates:
				row["wo" if holiday_dates[day] else "hl"] += 1
			else:
				row.nm += 1
		finish_row(row, len(days))
		rows.append(row)
	return rows


def add_leave(row, code, days):
	row[leave_field(code)] = row.get(leave_field(code), 0) + days


def count_attendance(row, a, leave_codes):
	code = leave_codes.get(a.leave_type) or UNSPECIFIED_LEAVE
	if a.status in WORKED:
		row.pr += 1
	elif a.status == "Half Day":
		row.pr += 0.5
		if a.leave_type:
			add_leave(row, code, 0.5)
		else:
			row.ab += 0.5
	elif a.status == "Absent":
		row.ab += 1
	elif a.status == "On Leave":
		add_leave(row, code, 1)

	row.late_count += 1 if a.late_entry else 0
	row.late_minutes += cint(a.late_minutes)
	row.under_time_minutes += cint(a.under_time_minutes)
	row.ot1_minutes += round(flt(a.custom_ot1_hours) * 60)
	row.ot2_minutes += round(flt(a.custom_ot2_hours) * 60)
	if a.status in WORKED or a.status == "Half Day":
		row.worked_minutes += round(flt(a.working_hours) * 60)


def finish_row(row, period_days):
	leaves = sum(v for k, v in row.items() if k.startswith("leave_"))
	row.total_days = sum(row[k] for k in DAY_COUNTS) + leaves
	row.balanced = 1 if abs(row.total_days + row.days_not_employed - period_days) < 0.001 else 0
	for fieldname, _label, total in DURATIONS:
		row[fieldname] = hh_mm(row[total])
		row[f"{fieldname}_hours"] = round(row[total] / 60, 2)  # decimal hours for payroll


def hh_mm(minutes):
	minutes = round(minutes or 0)
	return f"{minutes // 60:02d}:{minutes % 60:02d}"


# ---------------------------------------------------------------- totals and grouping


def total_row(rows, label, shown):
	total = frappe._dict(employee_name=label, is_total=1, balanced=1)
	for key in (*DAY_COUNTS, "late_count", "days_not_employed", "total_days", *(leave_field(c) for c in shown),
				*(t for _f, _l, t in DURATIONS)):
		total[key] = sum(flt(r.get(key)) for r in rows)
	for fieldname, _label, source in DURATIONS:
		total[fieldname] = hh_mm(total[source])
		total[f"{fieldname}_hours"] = round(total[source] / 60, 2)
	return total


def group_rows(rows, filters, shown):
	group_field = {"Department": "department", "Branch": "branch"}.get(filters.group_by)
	out = []
	if group_field:
		groups = defaultdict(list)
		for row in rows:
			groups[row[group_field]].append(row)
		for key in sorted(groups):
			out.extend(groups[key])
			out.append(total_row(groups[key], _("Subtotal: {0}").format(key), shown))
	else:
		out = list(rows)
	serial = 0
	for row in out:
		if not row.get("is_total"):
			serial += 1
			row.idx = serial
	if rows:
		out.append(total_row(rows, _("Grand Total"), shown))
	return out


# ---------------------------------------------------------------- columns


def get_columns(leave_codes):
	def col(label, fieldname, fieldtype="Float", width=70, **kw):
		return {"label": label, "fieldname": fieldname, "fieldtype": fieldtype, "width": width, **kw}

	columns = [
		col("#", "idx", "Int", 45),
		col(_("Employee ID"), "employee", "Link", 120, options="Employee"),
		col(_("Employee Name"), "employee_name", "Data", 180),
		col(_("Department"), "department", "Data", 150),
		col(_("Designation"), "designation", "Data", 140),
		col("PR", "pr", precision=1, width=60),
		col("AB", "ab", precision=1, width=60),
		col("WO", "wo", precision=1, width=60),
		col("HL", "hl", precision=1, width=60),
		col("NM", "nm", precision=1, width=60),
	]
	columns += [col(code, leave_field(code), precision=1, width=60) for code in leave_codes]
	columns.append(col(_("Late Count"), "late_count", "Int", 80))
	columns += [col(_(label), fieldname, "Data", 95) for fieldname, label, _total in DURATIONS]
	columns += [
		col(_("Total Days"), "total_days", precision=1, width=80),
		col(_("Days Not Employed"), "days_not_employed", "Int", 110),
	]
	# decimal hours for payroll: hidden on screen, included by "Include hidden columns" on export
	columns += [
		col(_(label.replace("(HH:MM)", "(Hours)")), f"{fieldname}_hours", precision=2, width=90, hidden=1)
		for fieldname, label, _total in DURATIONS
	]
	return columns
