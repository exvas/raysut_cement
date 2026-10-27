app_name = "raysut_cement"
app_title = "Raysut Cement"
app_publisher = "sammish"
app_description = "raysut_cement"
app_email = "sammish.thundiyil@gmail.com"
app_license = "mit"

# Apps
# ------------------

required_apps = ["frappe/erpnext", "frappe/hrms"]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "raysut_cement",
# 		"logo": "/assets/raysut_cement/logo.png",
# 		"title": "Raysut Cement",
# 		"route": "/raysut_cement",
# 		"has_permission": "raysut_cement.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/raysut_cement/css/raysut_cement.css"
# app_include_js = "/assets/raysut_cement/js/raysut_cement.js"

# include js, css files in header of web template
# web_include_css = "/assets/raysut_cement/css/raysut_cement.css"
# web_include_js = "/assets/raysut_cement/js/raysut_cement.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "raysut_cement/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
doctype_js = {
	"Employee Checkin": "public/js/employee_checkin.js",
	"Shift Type": "public/js/shift_type.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "raysut_cement/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "raysut_cement.utils.jinja_methods",
# 	"filters": "raysut_cement.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "raysut_cement.install.before_install"
# after_install = "raysut_cement.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "raysut_cement.uninstall.before_uninstall"
# after_uninstall = "raysut_cement.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "raysut_cement.utils.before_app_install"
# after_app_install = "raysut_cement.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "raysut_cement.utils.before_app_uninstall"
# after_app_uninstall = "raysut_cement.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "raysut_cement.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"raysut_cement.tasks.all"
# 	],
# 	"daily": [
# 		"raysut_cement.tasks.daily"
# 	],
# 	"hourly": [
# 		"raysut_cement.tasks.hourly"
# 	],
# 	"weekly": [
# 		"raysut_cement.tasks.weekly"
# 	],
# 	"monthly": [
# 		"raysut_cement.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "raysut_cement.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "raysut_cement.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "raysut_cement.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["raysut_cement.utils.before_request"]
# after_request = ["raysut_cement.utils.after_request"]

# Job Events
# ----------
# before_job = ["raysut_cement.utils.before_job"]
# after_job = ["raysut_cement.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"raysut_cement.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []


# CrossChex Cloud (ANVIZ devices) -> Employee Checkin
# ---------------------------------------------------

CROSSCHEX = "raysut_cement.raysut_cement"

scheduler_events = {
	"cron": {
		# Runs every minute; only syncs once Crosschex Settings.sync_frequency has elapsed
		"* * * * *": [f"{CROSSCHEX}.doctype.crosschex_settings.crosschex_settings.scheduled_attendance_sync"],
		# Re-read the last 2 days and import punches that never arrived
		"0 */4 * * *": [f"{CROSSCHEX}.crosschex_cloud.reconciliation.scheduled_reconciliation_job"],
	},
	"hourly": [f"{CROSSCHEX}.doctype.crosschex_settings.crosschex_settings.check_and_refresh_token"],
	"daily": [f"{CROSSCHEX}.doctype.crosschex_settings.crosschex_settings.purge_old_logs"],
}

# Keeps the webhook URL used by the older crosschex_cloud app working
override_whitelisted_methods = {
	"crosschex_cloud.api.attendance.make_attendace": f"{CROSSCHEX}.crosschex_cloud.api.attendance.make_attendace",
}

fixtures = [
	{"doctype": "Custom Field", "filters": [["module", "=", "Raysut Cement"]]},
	{"doctype": "Property Setter", "filters": [["module", "=", "Raysut Cement"]]},
]

# HikCentral-style scheduling: Timetable (Shift Type) -> Shift Pattern -> Schedule
# --------------------------------------------------------------------------------

boot_session = "raysut_cement.raysut_cement.settings.boot_session"

override_doctype_class = {"Shift Type": "raysut_cement.raysut_cement.overrides.shift_type.CustomShiftType"}

scheduler_events["daily"].append("raysut_cement.raysut_cement.scheduling.generator.daily_generation")
