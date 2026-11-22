# Testbox Studio

Ứng dụng desktop quản lý test case, dữ liệu kiểm thử và chạy automation cho
Project 3. Phiên bản hiện tại hỗ trợ Feature 003: Gradebook của Bùi Quốc Thái.

## Mở app và sử dụng nhanh

**Trên máy hiện tại**, môi trường `.venv` đã được cài sẵn. Mở PowerShell trong
thư mục project rồi chạy:

```powershell
Set-Location 'C:\Study\STesting\Pro3'
.\Start-App.ps1
```

Cũng có thể mở trực tiếp bằng Python, tiện xem thông báo nếu app không mở:

```powershell
.\.venv\Scripts\python.exe app.py
```

**Khi chuyển sang máy mới**, cài Python 3.12, mở terminal tại thư mục project
và thực hiện một lần:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\Start-App.ps1
```

Mở app không khởi động kiểm thử hay thay đổi Moodle. Cách sử dụng:

1. **Explorer:** chọn folder hoặc test case. Dùng **＋ Folder / ＋ Test case**
   để tạo mới; chuột phải hoặc **F2** để đổi tên; kéo thả, nút **↑ / ↓** hoặc
   **Move…** để di chuyển và sắp xếp. Có thể nhân bản, xóa và undo/redo.
2. **Import…:** chọn CSV, XLS hoặc XLSX. Có thể nạp trực tiếp workbook
   Project 2; file khác cần theo mẫu dữ liệu xuất từ app. Case trùng mã sẽ
   được cấp mã mới và giữ mã cũ trong `original_case_id`.
3. **Test data:** sửa dữ liệu nhập. **JSON / Expected** chứa tùy chọn nâng cao
   và kết quả mong đợi để kiểm tra. Thay dữ liệu nhập không tự đổi Expected
   Result; cần cập nhật kết quả mong đợi đúng với yêu cầu của case.
4. **Steps:** xem các bước tạo từ workflow và dữ liệu hiện tại; nhấp đúp một
   bước để đọc đầy đủ. **Source** hiển thị các bước gốc từ Excel để đối chiếu.
5. **Apply changes** áp dụng chỉnh sửa; **Save workspace** hoặc **Ctrl+S** lưu
   cây folder và test case vào `workspace/gradebook.project.json`. Dùng
   **File → Save workspace as…** để lưu một workspace khác.
6. **Export…:** chọn xuất phần đang chọn hoặc toàn workspace, rồi lưu dưới
   dạng `.csv`, `.xls` hoặc `.xlsx`. Xuất dữ liệu không thay thế thao tác lưu
   workspace; folder rỗng được giữ trong workspace JSON.
7. **Khi muốn chạy kiểm thử:** bật Moodle Project 2, kiểm tra URL/course và
   tài khoản có quyền sửa Gradebook. Trong **Run configuration**, chọn Level,
   trình duyệt và chế độ. Chọn **Selected items** hoặc **All cases**, rồi bấm
   **Run**. Chế độ Compatibility tự dùng Level 2 và Chrome/Edge cho 5 case
   quy định. Yêu cầu môi trường cụ thể nằm ở phần **Preconditions before a
   future run** bên dưới.
8. **Execution:** theo dõi Live steps và Case results; bấm **Open results** để
   mở file kết quả. **Stop after case** chờ case hiện tại và cleanup hoàn tất.

Nếu app đang mở khi mã nguồn được cập nhật, lưu các chỉnh sửa rồi đóng và mở
lại để thấy phiên bản mới. Tên app là **Testbox Studio**; tên feature, file dữ
liệu và workflow vẫn thể hiện đúng chức năng Gradebook hiện đang hỗ trợ.

## Project 3 — Feature 003: Gradebook — Bùi Quốc Thái

Python 3.12 + Selenium WebDriver + unittest. This submission implements the
36 manual grade-item cases from Project 2 as data-driven automation.

**Current state: desktop app, code and data prepared; browser tests NOT RUN.**
The desktop UI and file exchange have been checked offline. No Project 2
execution result is presented as a Project 3 result. Moodle has not been
started or changed during preparation.

The teacher's updated hint permits Python 3 and requires **at least one
non-functional requirement per student**, superseding the PDF's two-requirement
minimum. This implementation includes browser compatibility as that requirement.

## Desktop app — Testbox Studio

Open the app from PowerShell at the Pro3 root:

```powershell
.\Start-App.ps1
```

Or launch it directly using the prepared virtual environment:

```powershell
.\.venv\Scripts\pythonw.exe app.py
```

The interface uses a **Blender-inspired charcoal palette**, neutral grey
panels, blue selections/actions and an orange brand accent. Opening the app
only opens the workspace; it does not start browser tests.

The local `.venv` has the full pinned requirements installed, and `pip check`
reports no broken dependencies. Matching browser drivers are only requested
when an actual Run is started.

- **Explorer:** ordered folders and test cases; search, create, rename,
  duplicate, delete, move to another folder, drag/drop, and move up/down.
- **Test data:** edit case IDs, names, workflow, grade type, scale and bounds.
  Input whitespace is preserved. Changes are applied before selection,
  save, export or run; invalid JSON/data is rejected without discarding edits.
- **Steps:** a read-only preview generated from the effective workflow/data.
  Double-click a row to read its full action and expected result.
- **JSON / Expected:** edit extra input options and expected assertions
  independently. Changing an input never silently changes its expected value.
- **Source:** original Excel preconditions, notes, defect reference and manual
  steps. Imported manual steps are reference material; the Steps tab reflects
  the current executable Gradebook workflow.
- **Run configuration:** Level 1/2, Chrome/Edge/both, site/course, credentials,
  site JSON and functional/compatibility mode.
- **Execution:** live action events, per-case results and links to the actual
  output folder. Browser tests only start when **Run** is pressed. **Stop after
  case** finishes the active case and its cleanup rather than killing a browser.

The workspace is initially seeded with the 36 source cases grouped into five
workflow folders. Save writes to `workspace/gradebook.project.json`, separate
from the source CSV/Excel. File → Save as supports additional workspaces.
Tree changes have undo/redo; editing text also retains normal text undo.

Import/export supports real **CSV, XLS and XLSX** files. CSV uses UTF-8 with a
BOM. Export includes folder paths, order and imported source-step references;
import restores that hierarchy. Empty folders are retained in workspace JSON,
but a testcase table has no rows with which to represent an empty folder.
Duplicate IDs during import receive new IDs, with originals retained in the
`original_case_id` column. Imports are staged so a failed import does not
partially replace the workspace.

The original Project 2 workbook can be imported directly: its
`003 - Moodle Grading` sheet is recognized and converted using the same strict
extractor as the CLI. Other spreadsheets must use the exported data-driven
column schema. Excel formulas are not supported as XLSX test inputs; exported
values are literal text, including strings that start with `=`.

New cases start from one of the five supported Gradebook workflow templates.
This is a Gradebook automation app, not a universal Katalon recorder or an
arbitrary Selenium-step scripting tool. The steps preview is generated from
the workflow; it is not a second independently editable automation script.

Run uses an immutable CSV snapshot of the selected folders/cases in workspace
order, so edits made while running do not alter that invocation. Compatibility
mode always uses Level 2, both browsers, and the original fixed five case IDs.
Passwords are supplied to the child process environment and are not saved in
workspace JSON. A stopped/incomplete run is not reported as successful.

For another machine, install the app-only dependencies first if browser
execution is not needed yet:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-gui.txt
```

Install `requirements.txt` before using Run. Missing Selenium produces an
installation message; it does not prevent managing or exporting data.

Offline checks performed: CSV/XLS/XLSX round trips for all 36 cases, exact
three-space/256-character names, folder path retention, workspace save/load,
moving cases and rejecting cyclic folder moves, five workflow templates,
direct original Excel import, editor apply/undo/redo, Python syntax and GUI
startup/visual inspection. **No Moodle/Selenium suite was executed.**

## Files

```text
app.py                           Desktop application launcher
Start-App.ps1                    Launch without a console window
studio/                          Theme, tree model, import/export and desktop UI
level1/
  test_gradebook.py              Level 1 entry point
  settings.py                    URLs, locators and site settings in Python
  data/gradebook_cases.csv        36 cases, including expected results
level2/
  test_gradebook.py              Level 2 entry point
  config/site.json               URLs, locators and site settings supplied as data
  data/gradebook_cases.csv        36 cases, including expected results
gradebook/
  data.py                        CSV reader; preserves significant whitespace
  config.py                      Level-specific configuration loading
  browser.py                     Chrome/Edge creation
  page.py                        Shared Gradebook workflows and assertions
  runner.py                      unittest suite, cleanup and result reporting
nonfunctional/
  compatibility.py               Five cases on Chrome and Edge
tools/
  extract_gradebook.py            Reproducible extraction from Project 2 Excel
data/
  excel_snapshot.json             Original case descriptions, steps and oracles
  source_manifest.json            Workbook path, SHA-256 and extraction notes
requirements.txt                 Full dependencies, including browser runner
requirements-gui.txt             File editing / desktop dependencies only
```

Run commands from the **Pro3 root**, using `python -m ...`. Importing the
modules does not start a browser. Use these explicit runners rather than bare
`unittest discover`, which does not construct the CSV suite.

## Data source and extraction

Source: `../Pro2/CC01.G03-krecorder/Testcase-CC01.G03.xlsx`, sheet
`003 - Moodle Grading`. All 36 IDs, input values, manual steps and expected
results come from that workbook. The existing Project 2 Gradebook Recorder
was inspected to identify UI locators; no Katalon files are needed to run this
Python project.

To regenerate both CSV files and the provenance files, without a browser:

```powershell
python tools/extract_gradebook.py
```

Or supply another copy of the same workbook:

```powershell
python tools/extract_gradebook.py --source 'C:\path\Testcase-CC01.G03.xlsx'
```

This overwrites both level datasets, so preserve intentional CSV edits first.
The extractor supports this workbook's manual-step format and rejects unknown
actions. It does not attempt to infer arbitrary prose.

CSV common columns:

| Column | Meaning |
| --- | --- |
| `case_id`, `title`, `workflow` | Case identity and reusable execution flow |
| `item_name`, `minimum`, `maximum`, `grade_type` | Readable input data, read at runtime |
| `inputs_json` | Remaining fields, selections, checkboxes, dates and special-flow inputs |
| `expected_json` | Machine-readable expected field values, messages and control states |
| `expected_result` | All original per-step expected results from Excel, for traceability |
| `precondition`, `notes`, `known_defect` | Original setup requirements and defect information |
| `source_sheet`, `source_row` | Where the case starts in Excel |

`expected_json` is the executable oracle. `expected_result` is the original
human-readable oracle; editing that prose alone does not change assertions.
When changing a case intentionally, update its input columns/JSON and its
expected JSON independently. The runner never changes the oracle to match the
observed application response. `item_name`, `minimum`, `maximum` and
`grade_type` override their corresponding input JSON values.

The shared workflows are `create`, `validation`, `cancel`, `recover`, and
`duplicate`. Similar cases use the same Python workflow with different CSV
rows, rather than one copied script for each case. The two levels share this
Python implementation; their difference is where test items are defined.

Special values are preserved: an empty string, exactly three ASCII spaces,
256 uppercase X characters, negative/decimal numbers and blank numeric fields.
The empty-minimum-to-zero oracle comes from TC-003-022. Recovery error wording
comes from the relation-error cases in the same sheet. The JSON expands the
workbook's generic instructions to reopen the saved item and verify its fields.

## Preconditions before a future run

Use the existing Project 2 Moodle fixture, not a production course:

- Moodle at `http://127.0.0.1:9501`; Course 1 has course ID `2`.
- Teacher account has editing rights; English UI and Asia/Bangkok timezone.
- Minimum grade is enabled (`grade_report_showmin=1`).
- Gradebook uses the existing Natural aggregation configuration.
- Global scale `Separate and Connected ways of knowing` exists.
- No concurrent editing of the course while the suite runs.
- TC-003-030 retains the source date **31 December 2030, 12:00**. Once that
  future-date precondition expires, the runner records `SKIP`; it does not
  silently replace source data with another date.

The source preconditions are also present in each CSV row. This code does not
install Moodle, create the course, change site settings or restore backups.

## Installation for a future run

For a fresh machine, create the environment and install the full dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The requirements pin Selenium and openpyxl. openpyxl is only needed to
regenerate data; browser execution reads the prepared CSV using Python's
standard library. Selenium Manager handles matching browser drivers; its
first use may require internet access. Browser versions are recorded in the
results rather than assumed from the machine that prepared this code.

Default credentials are the existing local Project 2 fixture's `teacher01`
and `1234`. Override them through the environment when appropriate:

```powershell
$env:MOODLE_USERNAME = 'teacher01'
$env:MOODLE_PASSWORD = '1234'
```

## Offline listing — no tests and no browser

```powershell
python -m level1.test_gradebook --list
python -m level2.test_gradebook --list
python -m nonfunctional.compatibility --list
```

These commands only read data and print the planned cases. Listing does not
require Selenium. All browser commands below are opt-in for a later session.

## Level 1 — future execution

```powershell
.\.venv\Scripts\python.exe -m level1.test_gradebook
```

This runs all 36 CSV cases on Chrome, using URLs and locators from
`level1/settings.py`.

Example of selecting one case:

```powershell
.\.venv\Scripts\python.exe -m level1.test_gradebook --cases TC-003-011
```

## Level 2 — future execution

```powershell
.\.venv\Scripts\python.exe -m level2.test_gradebook
```

This runs all 36 CSV cases on Chrome, reading URLs and locators from
`level2/config/site.json`. It does not import the Level 1 settings for its
site configuration. To move the site or change a locator, edit the JSON or
provide a different JSON file:

```powershell
.\.venv\Scripts\python.exe -m level2.test_gradebook --config 'C:\path\site.json'
.\.venv\Scripts\python.exe -m level2.test_gradebook --base-url http://127.0.0.1:9501 --course-id 2
.\.venv\Scripts\python.exe -m level2.test_gradebook --browser edge
```

Each case gets a fresh browser session and a teacher login. Official runs use
a visible browser at 1440 × 900 and 100% zoom. `--headless` is available for
development, and its use is recorded in results.

## Non-functional requirement NF-003-COMPAT — future execution

Requirement: the selected Gradebook workflows work on **Chrome and Edge**
at 1440 × 900, with the necessary controls visible and operable.

Run:

```powershell
.\.venv\Scripts\python.exe -m nonfunctional.compatibility
```

The fixed sample is:

| Case | Coverage |
| --- | --- |
| TC-003-011 | Value type, custom numeric range |
| TC-003-012 | Scale type and named scale |
| TC-003-007 | Min equals Max validation |
| TC-003-018 | Recover from invalid bounds on the same form |
| TC-003-029 | Persist Hidden and Locked |

The script runs those five Level 2 cases on each browser: **10 executions**.
Pass requires all 10 executions and their cleanup to pass, with no skips.
Controls are located as visible elements and interacted with by Selenium;
saved values, errors and dependencies are checked against the CSV oracles.
The report includes browser versions and a requirement summary.

Both browsers use Chromium. Results support Chrome/Edge compatibility only,
not Firefox, Safari, other resolutions or all 36 cases. This NFR satisfies
the updated minimum of one requirement. The previously discussed performance
check is not implemented or claimed as completed in this version.

## Isolation, cleanup and the known defect

Runtime ID numbers are namespaced as `P3F003-<run token>-<case hash>`;
the original source ID remains in the CSV. This is fixture isolation, not a
change to the tested item-name or numeric boundary values. The duplicate-ID
scenario deliberately reuses the same runtime ID for its second submission.

Before a case, the runner records existing manual-item IDs. Afterward it
inspects newly added rows and deletes only rows whose reopened ID number
exactly matches that case's runtime ID. It never deletes baseline items or
unowned rows. Cleanup also runs when an assertion fails; a cleanup failure is
reported and cannot turn a failed case into a pass. If a run is interrupted,
use the recorded runtime ID to identify leftovers manually.

**TC-003-036 / F003-D01:** Expected behavior remains visible inline numeric
validation for empty Maximum grade. A database-error page is a **FAIL**.
The case is not skipped, marked as expected failure or changed to accept the
known defect. The old Project 2 result of 35/36 passing is not a result of
this code; no current execution outcome is known yet.

## Outputs after future execution

Each invocation creates its own folder under `results/`:

- `results.csv` and `results.json`: per-case status, expected results,
  failure details, browser version, runtime ID and total case duration.
- `unittest.log`: unittest output.
- `logs/`: operation and cleanup trace for each case.
- `evidence/`: failure screenshots and HTML captured before cleanup.
- `compatibility-summary.json`: only for the compatibility runner.

`PASS` means assertions and cleanup completed. `FAIL` means an assertion
failed, including an application result that violates its oracle. `ERROR`
means execution could not complete due to a script, environment or driver
error. `SKIP` always includes a reason. Any fail, error or skip gives a
nonzero process exit code. Total case duration includes setup/verification
and is **not a response-time benchmark**.

## Packaging

Keep `level1/` and `level2/` separated in the submission ZIP, and include
`gradebook/`, `nonfunctional/`, `data/`, `tools/`, `studio/`, `app.py`,
`Start-App.ps1`, the requirements files and this
README at the archive root. The shared Python package is required by both
levels; neither level folder is standalone. Do not include `.venv`, browser
drivers or Katalon projects. Add actual results and the PDF report after
running the tests in a later session.

## AI usage record for the eventual report

AI assistance was used to inspect the Project 2 workbook and Recorder,
design the data mapping, extract CSV data, and write/review the Python
automation, desktop app, file exchange and documentation. The tool was OpenAI Codex in this conversation.
No browser tests were executed during preparation. Use the actual prompts
and responses from the conversation in the final `AI Usage Declaration`;
do not use the statement that no AI assistance was used. This README is an
implementation record, not the final declaration or PDF report.

## API references consulted

- [Selenium WebDriverWait](https://www.selenium.dev/selenium/docs/api/py/selenium_webdriver_support/selenium.webdriver.support.wait.html)
- [Selenium Select](https://www.selenium.dev/selenium/docs/api/py/selenium_webdriver_support/selenium.webdriver.support.select.html)
- [Selenium package and driver setup](https://pypi.org/project/selenium/4.53.0/)
- [Tk themed widgets](https://docs.python.org/3.12/library/tkinter.ttk.html)
- [XLS reading with xlrd](https://xlrd.readthedocs.io/en/latest/)
- [XLS writing with xlwt](https://xlwt.readthedocs.io/en/latest/)
