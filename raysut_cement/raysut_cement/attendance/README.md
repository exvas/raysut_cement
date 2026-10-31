# Flexible Shift & Overtime

Switch: **Raysut Attendance Settings → Flexible Shift & Overtime** (on by default). Turned off,
Shift Types and Attendance behave as before.

## Shift Type settings (section "Flexible Shift & Overtime")

| Field | Meaning |
|---|---|
| Is Flexible Shift | No fixed start or end. The day's first punch is the IN, the last the OUT. |
| Day Start Time | When a new attendance day begins. A punch before it belongs to the previous date: with 05:00, a 02:30 punch on 11-Nov counts for 10-Nov. Required on a flexible shift. |
| Required Working Hours | Normal hours per day; more is overtime. Required on a flexible shift. On a fixed shift, blank means the start–end duration. |
| OT Min Hours | Overtime counts only when the extra hours reach this value. |
| OT Max Hours | Overtime per day is capped at this value (0 = no cap). |

On a flexible shift, Start/End Time are set from the Day Start (05:00 → 05:00 to 04:59) and the
check-in/check-out buffers are cleared; HR does not edit them. A shift can use either this or the
older Timetable Mode "Flexible", not both.

## How a flexible day is marked

- Shift for the day: the employee's Shift Assignment, else their Default Shift.
- The day's window is `[date + Day Start, next date + Day Start)`. Only windows that have ended are
  processed, so a day is marked once, with all its punches. Punches with "Skip Auto Attendance"
  (the imported TAMS history) are ignored, as are dates before the shift's Process Attendance After.
- Two or more punches: IN = first, OUT = last, worked hours = OUT − IN. Status is Present, or
  Absent / Half Day if the Shift Type's thresholds for those are set and not reached.
- One punch: Present with **Missing Punch** ticked, worked hours 0, no overtime. HR reviews these.
- No punches: nothing is created here; core auto attendance marks the day Absent, and never on a
  holiday.
- The punches are linked to the Attendance (Employee Checkin → Attendance).
- Submitted Attendance is left alone, unless "Re-process" is ticked: then it is cancelled and
  re-created (On Leave is always kept).

It runs every hour for the last 3 days, inside core auto attendance before its absent marking, and
from **Attendance list → Process Flexible Attendance** (date range, optional employee, Re-process).

## OT1 and OT2 (every Attendance, flexible or fixed)

Worked out on save and submit, from the Attendance's working hours and its shift:

- **Holiday** (the date is in the employee's Holiday List, else the company's: weekly offs such as
  Friday, and public holidays): Holiday Work ticked, **OT2 = all worked hours**, OT1 = 0. No min or
  max applies.
- **Working day**: `extra = worked − required`. OT1 = 0 if `extra < OT Min`; `OT Max` if
  `extra > OT Max` (and OT Max > 0); otherwise `extra`. OT2 = 0.
- Missing punch, Absent or On Leave: no overtime.
- Hours are rounded to 2 decimals.

Punches on a holiday now create Attendance (core HRMS would skip the day), so holiday work is paid.

## Report

**Consolidated Attendance** (Crenya Attendance → Reports): per employee for the chosen dates —
Present / Half / Absent / Leave days, Holiday Days Worked, Missing Punch days, Worked Hours,
OT1 (Normal OT) and OT2 (Holiday OT). Filters: company, dates (this month by default), branch,
department, employee. Employees come through the user's permissions, so a user restricted to a
branch or department sees only those. Export to Excel from the report menu.
