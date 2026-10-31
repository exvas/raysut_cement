# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class OTPolicy(Document):
	def validate(self):
		move, cap = flt(self.move_to_ot2_after_hours), flt(self.max_ot1_hours)
		if move and cap and cap > move:
			frappe.throw(_("Max OT1 per Day cannot exceed the hours after which OT1 moves to OT2"))
