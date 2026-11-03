# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Data for the Raysut Dashboard page: one day at a glance, plus the month so far."""

from collections import Counter, defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, date_diff, flt, get_first_day, getdate, nowdate

from raysut_cement.raysut_cement.report.consolidated_attendance.consolidated_attendance import get_employees

PRESENT = ("Present", "Work From Home")
TREND_DAYS = 14
MAX_TREND_DAYS = 62
MAX_DAYS = 366
MAX_ROWS = 2000
OT_MONTHS = 6


@frappe.whitelist()
def get_dashboard(from_date=None, to_date=None, company=None, department=None, employee=None):
	"""One day (from = to) or a date range at a glance, for the whole company, a department or one employee."""
	company = company or frappe.defaults.get_user_default("Company") or frappe.get_all("Company", pluck="name", limit=1)[0]
	employees = active_employees(company, department, employee)
	names = list(employees) or [""]

	requested_from, requested_to = date_range(from_date, to_date)
	start, end = requested_from, requested_to
	single = start == end
	if single and not frappe.db.exists("Attendance", {"attendance_date": end, "docstatus": 1, "employee": ("in", names)}):
		# nothing marked yet (attendance is created once the day is over): show the latest marked day
		latest = frappe.get_all(
			"Attendance",
			filters={"attendance_date": ("<=", end), "docstatus": 1, "employee": ("in", names)},
			pluck="attendance_date",
			order_by="attendance_date desc",
			limit=1,
		)
		start = end = getdate(latest[0]) if latest else end

	# one day is shown with the month so far; a range is its own period
	period_from = get_first_day(end) if single else start
	period = attendance_between(min(period_from, start), end, names)
	in_range = [r for r in period if start <= r.attendance_date <= end]
	cells = day_cells(company, employees, in_range, start, end)

	return {
		"company": company,
		"requested_from": requested_from,
		"requested_to": requested_to,
		"from_date": start,
		"to_date": end,
		"single": single,
		"period_from": period_from,
		"is_holiday": single and is_company_holiday(company, end),
		"kpi": day_kpis(employees, cells, in_range),
		"month": month_kpis([r for r in period if r.attendance_date >= period_from]),
		"locations": breakdown(employees, cells, "branch"),
		"departments": breakdown(employees, cells, "department")[:12],
		"trend": trend(names, add_days(end, -(TREND_DAYS - 1)) if single else start, end),
		"ot_by_month": ot_by_month(names, end),
		"top_overtime": top_overtime(employees, [r for r in period if r.attendance_date >= period_from]),
		"exceptions": exceptions(employees, in_range),
		"punches": punches_between(start, end, names),
	}


def date_range(from_date, to_date):
	end = getdate(to_date or nowdate())
	start = getdate(from_date) if from_date else end
	if start > end:
		start, end = end, start
	if date_diff(end, start) >= MAX_DAYS:
		frappe.throw(_("Pick a range of at most {0} days").format(MAX_DAYS))
	return start, end


def active_employees(company, department=None, employee=None):
	filters = frappe._dict(company=company, status="Active", department=department, employee=employee)
	return {e.name: e for e in get_employees(filters)}


def day_status(r):
	"""How the dashboard counts a day: a worked day with one punch is a missing punch, not present, until it is fixed."""
	if not r:
		return "not_marked"
	if r.custom_missing_punch and r.status in (*PRESENT, "Half Day"):
		return "missing_punch"
	return {"Absent": "absent", "On Leave": "on_leave", "Half Day": "half_day"}.get(r.status, "present" if r.status in PRESENT else None)


def day_cells(company, employees, rows, start, end):
	"""(employee, date, status, attendance) for every day of the range: the attendance, or not marked on a working day without one."""
	by_key = {(r.employee, r.attendance_date): r for r in rows}
	off = holidays_between(company, employees, start, end)
	days = [getdate(add_days(start, i)) for i in range(date_diff(end, start) + 1)]
	cells = []
	for name, e in employees.items():
		first = getdate(e.date_of_joining) if e.date_of_joining else start
		last = getdate(e.relieving_date) if e.relieving_date else end
		holidays = off[e.holiday_list or off["default"]]
		for day in days:
			r = by_key.get((name, day))
			if r:
				if status := day_status(r):
					cells.append((name, day, status, r))
			elif first <= day <= last and day not in holidays:
				cells.append((name, day, "not_marked", None))
	return cells


def holidays_between(company, employees, start, end):
	"""Holiday dates per holiday list; "default" names the company's list, for employees without their own."""
	default = frappe.get_cached_value("Company", company, "default_holiday_list")
	lists = {e.holiday_list for e in employees.values() if e.holiday_list} | ({default} if default else set())
	off = defaultdict(set, {"default": default})
	for h in frappe.get_all(
		"Holiday", filters={"parent": ("in", list(lists) or [""]), "holiday_date": ("between", [start, end])},
		fields=["parent", "holiday_date"],
	):
		off[h.parent].add(getdate(h.holiday_date))
	return off


DRILL_DOWN = {
	"present": lambda status, r: status == "present",
	"absent": lambda status, r: status == "absent",
	"on_leave": lambda status, r: status == "on_leave",
	"half_day": lambda status, r: status == "half_day",
	"not_marked": lambda status, r: status == "not_marked",
	"missing_punch": lambda status, r: status == "missing_punch",
	"late": lambda status, r: r and r.late_entry,
	"holiday_work": lambda status, r: r and r.custom_is_holiday_work,
}


@frappe.whitelist()
def get_kpi_employees(company, kpi, from_date=None, to_date=None, location=None, department=None, employee=None):
	"""The employees (one day) or employee-days (a range) behind a figure, counted exactly as on the cards."""
	if kpi != "active" and kpi not in DRILL_DOWN:
		frappe.throw(_("Unknown figure {0}").format(kpi))
	employees = active_employees(company, department, employee)
	if location:
		employees = {n: e for n, e in employees.items() if (e.branch or _("Not Set")) == location}
	start, end = date_range(from_date, to_date)

	def row(e, day=None, status=None, r=None):
		return {
			"employee": e.name, "employee_name": e.employee_name, "department": e.department, "designation": e.designation,
			"date": day, "attendance": r.name if r else None,
			"status": (_("Missing Punch") if status == "missing_punch" else r.status) if r else _("Not Marked"),
			"leave_type": r.leave_type if r else None, "in_time": r.in_time if r else None,
			"out_time": r.out_time if r else None, "working_hours": flt(r.working_hours, 2) if r else 0,
			"late_minutes": cint(r.late_minutes) if r else 0, "missing_punch": cint(r.custom_missing_punch) if r else 0,
		}

	if kpi == "active":
		out = [row(e) for e in employees.values()]
	else:
		rows = attendance_between(start, end, list(employees) or [""])
		out = [row(employees[name], day, status, r) for name, day, status, r in day_cells(company, employees, rows, start, end)
			   if DRILL_DOWN[kpi](status, r)]
	out.sort(key=lambda x: (x["department"] or "~", x["employee_name"] or ""))
	if start != end:
		out.sort(key=lambda x: x["date"] or start, reverse=True)
	return {"rows": out[:MAX_ROWS], "total": len(out)}


def punches_between(start, end, names):
	"""The punches of the employees shown; the last one tells whether the day's data is complete."""
	filters = {"time": ("between", [start, f"{end} 23:59:59"]), "employee": ("in", names)}
	last = frappe.get_all("Employee Checkin", filters=filters, pluck="time", order_by="time desc", limit=1)
	return {"count": frappe.db.count("Employee Checkin", filters), "last": last[0] if last else None, "last_sync": last_device_sync()}


def last_device_sync():
	value = frappe.db.get_single_value("Crosschex Settings", "last_sync_time")
	return value if value and getdate(value).year > 2000 else None  # never synced reads back as 0001-01-01


def attendance_between(start, end, names):
	return frappe.get_all(
		"Attendance",
		filters={"docstatus": 1, "attendance_date": ("between", [start, end]), "employee": ("in", names)},
		fields=["name", "employee", "attendance_date", "status", "leave_type", "late_entry", "late_minutes",
				"custom_missing_punch", "custom_is_holiday_work", "in_time", "out_time", "working_hours", "shift",
				"custom_worked_hours", "custom_ot1_hours", "custom_ot2_hours", "under_time_minutes"],
	)


def is_company_holiday(company, day):
	holiday_list = frappe.get_cached_value("Company", company, "default_holiday_list")
	return bool(holiday_list and frappe.db.exists("Holiday", {"parent": holiday_list, "holiday_date": day}))


def day_kpis(employees, cells, rows):
	status = Counter(c[2] for c in cells)
	return {
		"active": len(employees),
		"days": len(cells),
		"present": status["present"],
		"missing_punch": status["missing_punch"],
		"half_day": status["half_day"],
		"absent": status["absent"],
		"on_leave": status["on_leave"],
		"not_marked": status["not_marked"],
		"late": sum(1 for r in rows if r.late_entry),
		"holiday_work": sum(1 for r in rows if r.custom_is_holiday_work),
	}


def month_kpis(rows):
	worked = sum(
		flt(r.custom_worked_hours) or (flt(r.working_hours) if r.status in (*PRESENT, "Half Day") else 0) for r in rows
	)
	return {
		"worked_hours": round(worked, 1),
		"ot1_hours": round(sum(flt(r.custom_ot1_hours) for r in rows), 1),
		"ot2_hours": round(sum(flt(r.custom_ot2_hours) for r in rows), 1),
		"under_time_hours": round(sum(cint(r.under_time_minutes) for r in rows) / 60, 1),
		"late_days": sum(1 for r in rows if r.late_entry),
		"missing_punch_days": sum(1 for r in rows if r.custom_missing_punch),
	}


def breakdown(employees, cells, field):
	"""Headcount and the statuses (days, for a range) per branch (location) or department."""
	groups = defaultdict(Counter)
	for e in employees.values():
		groups[e.get(field) or _("Not Set")]["headcount"] += 1
	for name, _day, status, _r in cells:
		groups[employees[name].get(field) or _("Not Set")][status] += 1
	out = []
	keys = ("present", "missing_punch", "absent", "on_leave", "half_day", "not_marked")
	for name, c in groups.items():
		row = {"name": name, "headcount": c["headcount"], **{k: c[k] for k in keys}}
		total = sum(c[k] for k in keys)
		row["present_pct"] = round(100 * (c["present"] + 0.5 * c["half_day"]) / total) if total else 0
		out.append(row)
	return sorted(out, key=lambda r: -r["headcount"])


def trend(names, start, end):
	"""Statuses per day, or per month for a long range."""
	monthly = date_diff(end, start) >= MAX_TREND_DAYS
	key = (lambda d: d.strftime("%Y-%m")) if monthly else (lambda d: d)
	counts = defaultdict(Counter)
	for r in frappe.get_all(
		"Attendance",
		filters={"docstatus": 1, "employee": ("in", names), "attendance_date": ("between", [start, end])},
		fields=["attendance_date", "status", "custom_missing_punch"],
	):
		counts[key(r.attendance_date)][day_status(r)] += 1
	if monthly:
		buckets = []
		month = get_first_day(start)
		while month <= end:
			buckets.append(month)
			month = getdate(add_months(month, 1))
		labels = [m.strftime("%b %Y") for m in buckets]
	else:
		buckets = [getdate(add_days(start, i)) for i in range(date_diff(end, start) + 1)]
		labels = [d.strftime("%d %b") for d in buckets]
	buckets = [key(b) for b in buckets]
	return {
		"monthly": monthly,
		"labels": labels,
		**{k: [counts[b][k] for b in buckets] for k in ("present", "missing_punch", "absent", "on_leave")},
	}


def ot_by_month(names, day):
	start = get_first_day(add_months(day, -(OT_MONTHS - 1)))
	totals = defaultdict(lambda: [0.0, 0.0])
	for r in frappe.get_all(
		"Attendance",
		filters={"docstatus": 1, "employee": ("in", names), "attendance_date": ("between", [start, day]),
				 "custom_worked_hours": (">", 0)},
		fields=["attendance_date", "custom_ot1_hours", "custom_ot2_hours"],
	):
		key = r.attendance_date.strftime("%Y-%m")
		totals[key][0] += flt(r.custom_ot1_hours)
		totals[key][1] += flt(r.custom_ot2_hours)
	months = [getdate(add_months(start, i)) for i in range(OT_MONTHS)]
	return {
		"labels": [m.strftime("%b %Y") for m in months],
		"ot1": [round(totals[m.strftime("%Y-%m")][0]) for m in months],
		"ot2": [round(totals[m.strftime("%Y-%m")][1]) for m in months],
	}


def top_overtime(employees, rows, limit=10):
	totals = defaultdict(lambda: [0.0, 0.0])
	for r in rows:
		totals[r.employee][0] += flt(r.custom_ot1_hours)
		totals[r.employee][1] += flt(r.custom_ot2_hours)
	ranked = sorted(totals.items(), key=lambda item: -(item[1][0] + item[1][1]))[:limit]
	return [
		{"employee": name, "employee_name": employees[name].employee_name, "department": employees[name].department,
		 "ot1": round(ot1, 1), "ot2": round(ot2, 1)}
		for name, (ot1, ot2) in ranked if ot1 + ot2 > 0
	]


def exceptions(employees, rows, limit=15):
	"""Late arrivals and missing punches, latest first, for follow-up."""
	out = []
	for r in rows:
		if r.custom_missing_punch or r.late_entry:
			e = employees[r.employee]
			out.append(
				{"employee": r.employee, "employee_name": e.employee_name, "department": e.department, "date": r.attendance_date,
				 "issue": _("Missing Punch") if r.custom_missing_punch else _("Late {0} min").format(cint(r.late_minutes)),
				 "in_time": r.in_time}
			)
	out.sort(key=lambda x: x["issue"])
	out.sort(key=lambda x: x["date"], reverse=True)
	return out[:limit]
