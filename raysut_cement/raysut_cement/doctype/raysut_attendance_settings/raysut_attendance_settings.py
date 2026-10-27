# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class RaysutAttendanceSettings(Document):
	def on_update(self):
		# features are read into frappe.boot; make open sessions pick up the change
		frappe.clear_cache()
