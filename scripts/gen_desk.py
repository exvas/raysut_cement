"""Generate the Frappe 16 desk files (desktop tile, Dock, Sidebars) for raysut_cement.

Edit SPEC, run from the repo root (apps/raysut_cement/): `python3 scripts/gen_desk.py`,
then `bench --site <site> migrate`. SPEC is the source of truth; don't hand-edit the JSON.
"""

import datetime
import json
import os
import re

SPEC = {
	"app": "raysut_cement",
	"app_title": "Raysut Cement",
	"logo": "/assets/raysut_cement/images/raysut-cement-logo.svg",
	"tiles": [{"label": "Raysut Cement", "link": "auto"}],
	# One module ("Raysut Cement") with several areas, so each title is a distinct, non-module name
	"rail": [
		{
			"title": "Crenya Attendance",
			"module": "Raysut Cement",
			"icon": "calendar-check",
			"items": [
				("workspace", "Home", "Crenya Attendance", "house"),
				("doctype", "Employee Checkin", "Employee Checkin", "pointer"),
				("doctype", "Attendance", "Attendance", "user-check"),
				("doctype", "Shift Assignment", "Shift Assignment", "calendar-days"),
				("section", "Reports", "notepad-text", [
					("report", "Consolidated Attendance", "Consolidated Attendance"),
					("report", "Daily Attendance", "Daily Attendance"),
					("report", "Under Time", "Under Time"),
					("report", "Shift Roster", "Shift Roster"),
					("report", "Flexible Shift Work Hours", "Flexible Shift Work Hours"),
					("report", "Monthly Attendance Sheet", "Monthly Attendance Sheet"),
				]),
				("doctype", "Settings", "Raysut Attendance Settings", "settings"),
			],
		},
		{
			"title": "Shift Scheduling",
			"module": "Raysut Cement",
			"icon": "calendar-clock",
			"items": [
				("report", "Schedule Overview", "Shift Roster", "calendar-range"),
				("doctype", "Schedule", "Shift Pattern Assignment", "calendar-check"),
				("doctype", "Shift", "Shift Pattern", "layers"),
				("doctype", "Timetable", "Shift Type", "clock"),
				("doctype", "Break Timetable", "Break Timetable", "coffee"),
				("doctype", "OT Policy", "OT Policy", "timer"),
				("section", "Reports", "notepad-text", [
					("report", "Daily Attendance", "Daily Attendance"),
					("report", "Consolidated Attendance", "Consolidated Attendance"),
					("report", "Under Time", "Under Time"),
				]),
			],
		},
		{
			"title": "Attendance Devices",
			"module": "Raysut Cement",
			"icon": "tablet-smartphone",
			"items": [
				("doctype", "CrossChex Settings", "Crosschex Settings", "settings"),
				("doctype", "CrossChex Log", "CrossChex Log", "list-checks"),
				("doctype", "Employee Checkin", "Employee Checkin", "pointer"),
				("section", "Reports", "notepad-text", [
					("report", "Daily Attendance", "Daily Attendance"),
					("report", "Consolidated Attendance", "Consolidated Attendance"),
					("report", "Under Time", "Under Time"),
				]),
			],
		},
	],
}

NOW = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
ROOT = SPEC["app"]
FLAGS = {
	"added": 0, "child": 0, "collapsible": 1, "hidden": 0, "indent": 0,
	"is_default_module": 0, "keep_closed": 0, "open_in_new_tab": 0, "show_arrow": 0,
}
TYPES = {"doctype": "DocType", "report": "Report", "workspace": "Workspace", "page": "Page", "dashboard": "Dashboard"}


def scrub(s):
	return s.replace(" ", "_").replace("-", "_").lower()


def slug(s):
	return re.sub(r"\s+", "-", s.lower().replace("&", " and ").strip())


def meta(doctype, name):
	return {
		"app": SPEC["app"], "creation": NOW, "modified": NOW, "docstatus": 0, "idx": 0, "doctype": doctype,
		"name": name, "owner": "Administrator", "modified_by": "Administrator", "standard": 1,
	}


def dump(path, doc):
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w") as f:
		f.write(json.dumps(doc, indent=1, sort_keys=True) + "\n")
	print("wrote", path)


def link(kind, label, target, icon=None, child=0):
	row = {**FLAGS, "type": "Link", "label": label, "child": child}
	if kind == "url":
		row.update(link_type="URL", url=target)
	else:
		row.update(link_type=TYPES[kind], link_to=target)
	if icon:
		row["icon"] = icon
	return row


def rows(items):
	out = []
	for it in items:
		if it[0] == "section":
			_, label, icon, children = it
			out.append({**FLAGS, "type": "Section Break", "label": label, "icon": icon,
						"link_type": "DocType", "indent": 1, "keep_closed": 1})
			out += [link(*c, child=1) for c in children]
		else:
			out.append(link(*it))
	return [{"doctype": "Sidebar Item", "parentfield": "items", "parenttype": "Sidebar", "idx": i, **r}
			for i, r in enumerate(out, 1)]


bad = [r["title"] for r in SPEC["rail"] if re.search(r"[/?#%\\]", r["title"])]
assert not bad, f"unroutable characters in titles: {bad}"
assert len({slug(r["title"]) for r in SPEC["rail"]}) == len(SPEC["rail"]), "duplicate slugs"

for r in SPEC["rail"]:
	doc = meta("Sidebar", r["title"])
	doc.update(title=r["title"], module=r["module"], header_icon=r["icon"], items=rows(r["items"]))
	s = scrub(r["title"])
	dump(f"{ROOT}/{scrub(r['module'])}/sidebar/{s}/{s}.json", doc)

dock = meta("Dock", SPEC["app"])
dock.update(user="", items=[{"added": 0, "hidden": 0, "icon": r["icon"], "link_type": "Sidebar",
							 "link_to": r["title"], "title": r["title"]} for r in SPEC["rail"]])
dump(f"{ROOT}/dock/{SPEC['app']}/{SPEC['app']}.json", dock)

first_url = "/desk/" + slug(SPEC["rail"][0]["title"])
for n, t in enumerate(SPEC["tiles"]):
	tile = meta("Desktop Icon", t["label"])
	tile.update(label=t["label"], icon_type="App", link_type="External", hidden=0, idx=20 + n,
				link=first_url if t["link"] == "auto" else t["link"], logo_url=t.get("logo", SPEC["logo"]), roles=[])
	dump(f"{ROOT}/desktop_icon/{scrub(t['label'])}.json", tile)

print(f"\nSet hooks.add_to_apps_screen route to: {first_url}")
