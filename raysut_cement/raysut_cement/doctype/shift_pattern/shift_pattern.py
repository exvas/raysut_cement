# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.model.document import Document
from frappe.utils import cint

from raysut_cement.raysut_cement.scheduling.pattern import TIMETABLE_FIELDS, validate_pattern
from raysut_cement.raysut_cement.scheduling.timetable import window_minutes
from raysut_cement.raysut_cement.settings import is_enabled

REPEAT_FIELDS = ("repeat_mode", "repeat_every", "week_starts_on")


class ShiftPattern(Document):
	def validate(self):
		for row in self.days:
			row.cycle_index = cint(row.cycle_index) or 1
		self.set_sequence()
		validate_pattern(self)

	def set_sequence(self):
		counters = {}
		for row in sorted(self.days, key=lambda r: (cint(r.cycle_index), r.day_key, cint(r.sequence), r.idx)):
			key = (row.cycle_index, row.day_key)
			counters[key] = counters.get(key, 0) + 1
			row.sequence = counters[key]

	def on_update(self):
		before = self.get_doc_before_save()
		if not is_enabled("enable_shift_scheduling"):
			return
		if before and self.schedule_signature(before) != self.schedule_signature(self):
			frappe.enqueue(
				"raysut_cement.raysut_cement.scheduling.generator.regenerate_for_pattern",
				pattern_name=self.name,
				queue="long",
				enqueue_after_commit=True,
				now=frappe.flags.in_test,
			)

	@staticmethod
	def schedule_signature(doc):
		return (
			tuple(doc.get(f) for f in REPEAT_FIELDS),
			sorted((cint(r.cycle_index), r.day_key, r.timetable) for r in doc.days),
		)


@frappe.whitelist()
def get_timetable_details(names):
	"""Colour and time range (minutes from midnight, end may pass 1440) for the grid."""
	if isinstance(names, str):
		names = json.loads(names)
	details = []
	for shift in frappe.get_all("Shift Type", filters={"name": ("in", names or [""])}, fields=TIMETABLE_FIELDS):
		start, end = window_minutes(shift)
		details.append({"name": shift.name, "color": shift.shift_color or "#5e64ff", "mode": shift.shift_mode or "Normal", "start": start, "end": end})
	return details
