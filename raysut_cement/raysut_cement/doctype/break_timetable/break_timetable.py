# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class BreakTimetable(Document):
	def validate(self):
		if self.break_type == "Fixed":
			if not (self.break_start and self.break_end):
				frappe.throw(_("Break Start and Break End are required for a Fixed break"))
			if self.break_start == self.break_end:
				frappe.throw(_("Break Start and Break End cannot be the same"))
			self.break_duration_minutes = 0
		else:
			if cint(self.break_duration_minutes) <= 0:
				frappe.throw(_("Break Duration must be greater than zero for a Flexible break"))
			self.break_start = self.break_end = None
