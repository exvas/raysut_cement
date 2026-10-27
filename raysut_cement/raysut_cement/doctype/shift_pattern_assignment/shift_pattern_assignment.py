# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_link_to_form, getdate

from raysut_cement.raysut_cement.scheduling.generator import clear_future, generate, resolve_employees


class ShiftPatternAssignment(Document):
	def validate(self):
		if self.end_date and getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("End Date cannot be before Start Date"))
		if not 1 <= cint(self.generation_horizon_days) <= 366:
			frappe.throw(_("Generate Days Ahead must be between 1 and 366"))

		employees = resolve_employees(self)
		self.set("employees", [{"employee": e.name, "employee_name": e.employee_name} for e in employees])
		if self.status == "Active":
			self.validate_no_overlapping_schedule(employees)
		self.warn_default_shift(employees)

	def validate_no_overlapping_schedule(self, employees):
		mine = {e.name for e in employees}
		others = frappe.get_all(
			"Shift Pattern Assignment",
			filters={"docstatus": 1, "status": "Active", "name": ("!=", self.name)},
			fields=["name", "start_date", "end_date"],
		)
		for other in others:
			if self.end_date and getdate(other.start_date) > getdate(self.end_date):
				continue
			if other.end_date and getdate(other.end_date) < getdate(self.start_date):
				continue
			clash = mine & {e.name for e in resolve_employees(frappe.get_doc("Shift Pattern Assignment", other.name))}
			if clash:
				frappe.throw(
					_("{0} already has an active schedule {1} in this period").format(
						frappe.bold(sorted(clash)[0]), get_link_to_form("Shift Pattern Assignment", other.name)
					)
				)

	def warn_default_shift(self, employees):
		with_default = [e.name for e in employees if e.default_shift]
		if with_default and not self.flags.in_generation:
			frappe.msgprint(
				_("These employees have a Default Shift: {0}. On rest days HRMS falls back to the default shift and may mark them Absent. Clear the Default Shift on these employees.").format(
					", ".join(with_default[:10]) + (" ..." if len(with_default) > 10 else "")
				),
				title=_("Default Shift found"),
				indicator="orange",
			)

	def on_submit(self):
		generate(self)

	def before_cancel(self):
		# generated Shift Assignments link back here; they are handled in on_cancel
		self.ignore_linked_doctypes = ("Shift Assignment",)

	def on_cancel(self):
		clear_future(self)

	def on_update_after_submit(self):
		before = self.get_doc_before_save()
		if not before or self.flags.in_generation:
			return
		if before.status == "Active" and self.status == "Inactive":
			clear_future(self)
		elif self.status == "Active" and (
			before.status != "Active" or cint(before.generation_horizon_days) != cint(self.generation_horizon_days)
		):
			self.flags.in_generation = True
			generate(self)


@frappe.whitelist()
def regenerate_now(name):
	doc = frappe.get_doc("Shift Pattern Assignment", name)
	doc.check_permission("write")
	from raysut_cement.raysut_cement.scheduling.generator import regenerate

	regenerate(doc)
	return doc.last_generated_on
