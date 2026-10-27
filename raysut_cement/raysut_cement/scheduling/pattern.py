# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Shift Pattern cycle maths: which timetables apply on a given date."""

from collections import defaultdict
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, getdate

from raysut_cement.raysut_cement.scheduling.timetable import window_minutes

WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
MAX_REPEAT = {"Week": 4, "Day": 31, "Month": 3}
TIMETABLE_FIELDS = ["name", "shift_mode", "start_time", "end_time", "valid_period_start", "valid_period_end", "valid_period_end_day", "shift_color"]


def weekday_name(date):
	return WEEKDAYS[(date.weekday() + 1) % 7]  # python: Monday=0


def ordered_week(week_starts_on):
	i = WEEKDAYS.index(week_starts_on or "Sunday")
	return WEEKDAYS[i:] + WEEKDAYS[:i]


def cycle_slots(pattern):
	"""Every (cycle_index, day_key) of the cycle in display order."""
	n = cint(pattern.repeat_every) or 1
	if pattern.repeat_mode == "Day":
		return [(i, f"Day {i}") for i in range(1, n + 1)]
	if pattern.repeat_mode == "Month":
		return [(m, str(d)) for m in range(1, n + 1) for d in range(1, 32)]
	return [(w, day) for w in range(1, n + 1) for day in ordered_week(pattern.week_starts_on)]


def slot_for_date(pattern, anchor, date):
	"""Position of `date` in a cycle that starts on `anchor`; None before the anchor."""
	anchor, date = getdate(anchor), getdate(date)
	if date < anchor:
		return None
	n = cint(pattern.repeat_every) or 1
	if pattern.repeat_mode == "Day":
		return ((date - anchor).days % n + 1, f"Day {(date - anchor).days % n + 1}")
	if pattern.repeat_mode == "Month":
		months = (date.year - anchor.year) * 12 + date.month - anchor.month
		return (months % n + 1, str(date.day))
	week_start = anchor - timedelta(days=ordered_week(pattern.week_starts_on).index(weekday_name(anchor)))
	return ((date - week_start).days // 7 % n + 1, weekday_name(date))


def rows_by_slot(pattern):
	slots = defaultdict(list)
	for row in sorted(pattern.days, key=lambda r: (cint(r.cycle_index), cint(r.sequence))):
		slots[(cint(row.cycle_index), row.day_key)].append(row.timetable)
	return slots


def timetables_for_date(pattern, anchor, date, slots=None):
	slot = slot_for_date(pattern, anchor, date)
	if not slot:
		return []
	return (slots or rows_by_slot(pattern)).get(slot, [])


def get_timetable(name):
	return frappe.get_cached_value("Shift Type", name, TIMETABLE_FIELDS, as_dict=True)


def timetable_range(name):
	shift = get_timetable(name)
	if not shift:
		frappe.throw(_("Timetable {0} does not exist").format(name))
	return window_minutes(shift)


def next_slots(pattern, slot):
	"""Slots that follow `slot` on the calendar (for cross-midnight overlap checks)."""
	cycle_index, day_key = slot
	n = cint(pattern.repeat_every) or 1
	if pattern.repeat_mode == "Month":
		day = int(day_key)
		following = [(cycle_index, str(day + 1))] if day < 31 else []
		if day >= 28:  # month ends on the 28th-31st; the next day is the 1st of the next month
			following.append((cycle_index % n + 1, "1"))
		return following
	slots = cycle_slots(pattern)
	return [slots[(slots.index(slot) + 1) % len(slots)]]


def validate_pattern(pattern):
	if pattern.repeat_mode not in MAX_REPEAT:
		frappe.throw(_("Repeat By must be Week, Day or Month"))
	if not 1 <= cint(pattern.repeat_every) <= MAX_REPEAT[pattern.repeat_mode]:
		frappe.throw(
			_("For {0}, Repeat Every must be between 1 and {1}").format(pattern.repeat_mode, MAX_REPEAT[pattern.repeat_mode])
		)

	valid = set(cycle_slots(pattern))
	for row in pattern.days:
		if (cint(row.cycle_index), row.day_key) not in valid:
			frappe.throw(_("Row {0}: {1} is not part of this cycle").format(row.idx, row.day_key))
	if not pattern.days:
		frappe.throw(_("Assign a timetable to at least one day. Days without a timetable are rest days."))

	slots = rows_by_slot(pattern)
	for slot, names in slots.items():
		ranges = sorted((timetable_range(n), n) for n in names)
		for (a, a_name), (b, b_name) in zip(ranges, ranges[1:]):
			if b[0] < a[1]:
				frappe.throw(_("{0}: timetables {1} and {2} overlap").format(slot_label(pattern, slot), a_name, b_name))

		for name in names:
			start, end = timetable_range(name)
			if end <= 1440:
				continue
			for following in next_slots(pattern, slot):
				next_names = slots.get(following) or []
				if not next_names:
					continue
				first = min((timetable_range(n), n) for n in next_names)
				if first[0][0] + 1440 < end:
					frappe.throw(
						_("{0} runs past midnight and overlaps {1} on {2}").format(name, first[1], slot_label(pattern, following))
					)


def slot_label(pattern, slot):
	cycle_index, day_key = slot
	if pattern.repeat_mode == "Week":
		return f"Week {cycle_index} {day_key}"
	if pattern.repeat_mode == "Month":
		return f"Month {cycle_index} Day {day_key}"
	return day_key
