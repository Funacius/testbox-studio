# Testbox Studio

Ứng dụng desktop để soạn bước automation, quản lý dataset và chạy kiểm thử
browser theo dữ liệu. Testcase mới dùng workflow **steps**, có thể chỉnh sửa
trực tiếp hành động và assertion. Bộ Gradebook Feature003 vẫn được giữ như
một bộ workflow riêng để sử dụng các case Project 3 hiện có.

## Testcase dùng chung — Steps có thể sửa

1. Dùng **File → New workspace** nếu muốn project mới; hoặc thêm vào workspace
   hiện tại. Bấm **＋ Test case**, chọn workflow **steps**.
2. Trong **Steps**, dùng **＋ Step / Edit / Copy / Delete**, kéo đổi thứ tự,
   bật/tắt bước và Undo/Redo. Mỗi bước có action, target, value, expected,
   timeout và phase. `setup` chạy trước; `cleanup` vẫn chạy sau khi testcase lỗi.
3. Trong **Test data**, sửa bảng **Data rows**, bảng **Variables** và mô tả.
   Nhấp đúp cell để sửa; giá trị trống, dấu cách và số có zero ở đầu được giữ
   khi nguồn lưu dưới dạng text. Dùng `${column}` trong bước để đọc dataset.
4. Target có thể là `id=username`, `css=#submit`, `xpath=//button` hoặc alias
   `@login_button`. Alias và biến dùng chung hiện được sửa trong
   **Project settings…** bằng JSON; giao diện locator library là phần tiếp theo.
5. Chọn Base URL, browser và Headless, bấm **Check connection**, rồi **Run**.
   **Save environment…** lưu URL/browser/viewport/timeout để chọn lại. Mật khẩu
   nhập trong Run configuration được truyền bằng environment của tiến trình con.
   Giá trị từng dòng dataset được ưu tiên hơn credential mặc định, nên có thể
   kiểm tra cả đăng nhập hợp lệ và không hợp lệ.
6. Với `type`, browser có thể giới hạn hoặc chuẩn hóa input; dùng `assert_value`
   để kiểm tra kết quả mong đợi. `type_exact` yêu cầu giữ nguyên input tuyệt đối.
   Locator dùng cho một hành động phải xác định duy nhất phần tử phù hợp.

Workspace format 2 mở được file format 1 và giữ nguyên case/expected/source cũ.
Khi Save lần đầu lên file format 1, app giữ bản sao `.v1.backup.json` bên cạnh.
Nếu app cũ đang mở, lưu workspace rồi đóng app cũ trước khi mở phiên bản mới.

### Import file của người khác

**Import…** mở wizard để chọn sheet, dòng header, mode, mapping và Preview:

- **Steps table:** map Case ID, Action, Target, Value, Expected… vào cột tương
  ứng. Case nhiều dòng có thể để trống ID ở các dòng tiếp theo. Mô tả hành động
  bằng lời được giữ thành `note` tắt sẵn; cần chuyển thành action rõ ràng trước
  khi Run. File chỉ có ghi chú không được báo là một testcase chạy PASS.
- **Dataset:** nhập các cột thành biến. Preview hiển thị tên biến sau chuẩn hóa.
  Có thể thay dataset của case **steps** đang chọn hoặc tạo case nháp mới.
- **Testbox export:** nhập lại bảng đã xuất từ app, giữ cấu trúc case/folder/steps.
- **Project 2 Gradebook:** chọn rõ sheet `003 - Moodle Grading` để dùng adapter
  cũ. App không tự chọn phần Gradebook thay cho sheet của thành viên khác.

Mapping có thể lưu theo tên profile trong project. Import được kiểm tra trước
khi áp dụng; lỗi dòng/cột không làm thay một phần workspace. Công thức XLSX
trong vùng dữ liệu cần đổi thành giá trị literal trước khi nhập.

### Thử luồng chung bằng website mẫu

Mở terminal riêng tại thư mục Pro3 và chạy:

```powershell
.\.venv\Scripts\python.exe tools/demo_site.py
```

Trong app, nhập `examples/login-steps.csv` bằng **Steps table**. Chọn case
`DEMO-LOGIN`, nhập `examples/login-data.csv` bằng **Dataset** vào case đó.
Đặt Base URL là `http://127.0.0.1:9542`, Apply changes rồi Run. Ba dòng dữ liệu
gồm một đăng nhập hợp lệ và hai đăng nhập không hợp lệ; cả ba có expected riêng.
Website mẫu không cần Moodle/Docker và chỉ phục vụ ví dụ automation cục bộ.

### Tiến độ mở rộng app

Đã triển khai phần lõi: testcase Steps dùng chung, bộ chạy, editor Steps,
import mapping, bảng dataset/biến, cấu hình môi trường và kiểm tra kết nối.
Các phần đang tiếp tục: locator library, pause/step/breakpoints, báo cáo tổng
hợp và Python export, cấu hình NFR chung, templates/recorder/điều kiện/vòng lặp.
`data/studio-development.json` theo dõi phạm vi và các kiểm chứng tương ứng.
Breakpoint hiện được lưu trong step; điều khiển dừng ở breakpoint chưa được nối
với bộ chạy. Chế độ Compatibility hiện vẫn là preset Gradebook Level 2.

Kiểm chứng bước đầu cho phần lõi được ghi riêng tại
[studio-core-verification.json](artifacts/studio-core-verification.json):
26 development tests PASS, gồm cả chạy Chrome trên website mẫu cục bộ. Đây là
kiểm tra app, tách biệt với kết quả 36 testcase Gradebook của Project 3.
Chạy lại các kiểm tra phát triển bằng:

```powershell
$env:TESTBOX_BROWSER_TESTS = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

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
2. **Import…:** chọn CSV, XLS hoặc XLSX, rồi chọn sheet/mapping trong wizard.
   Workbook Project 2 có adapter Gradebook riêng. Case trùng mã sẽ
   được cấp mã mới và giữ mã cũ trong `original_case_id`.
3. **Test data:** sửa dữ liệu nhập. **JSON / Expected** chứa tùy chọn nâng cao
   và kết quả mong đợi để kiểm tra. Thay dữ liệu nhập không tự đổi Expected
   Result; cần cập nhật kết quả mong đợi đúng với yêu cầu của case.
4. **Steps:** case workflow **steps** sửa trực tiếp các bước thực thi. Với
   workflow Gradebook cũ, tab này vẫn là bản xem trước sinh từ dữ liệu.
   **Source** hiển thị các bước gốc từ Excel để đối chiếu.
5. **Apply changes** áp dụng chỉnh sửa; **Save workspace** hoặc **Ctrl+S** lưu
   cây folder và test case vào `workspace/gradebook.project.json`. Dùng
   **File → Save workspace as…** để lưu một workspace khác.
6. **Export…:** chọn xuất phần đang chọn hoặc toàn workspace, rồi lưu dưới
   dạng `.csv`, `.xls` hoặc `.xlsx`. Xuất dữ liệu không thay thế thao tác lưu
   workspace; folder rỗng được giữ trong workspace JSON.
7. **Khi muốn chạy kiểm thử:** bật Moodle Project 2, kiểm tra URL/course và
   tài khoản có quyền sửa Gradebook. Trong **Run configuration**, chọn Level,
   trình duyệt và chế độ. **Headless (background)** mặc định bật để chạy nền.
   Chọn **Selected items** hoặc **All cases**, rồi bấm
   **Run**. Chế độ Compatibility tự dùng Level 2 và Chrome/Edge cho 5 case
   quy định. Yêu cầu môi trường cụ thể nằm ở phần **Moodle preconditions**
   bên dưới.
8. **Execution:** theo dõi Live steps và Case results; bấm **Open results** để
   mở file kết quả. **Stop after case** chờ case hiện tại và cleanup hoàn tất.

Nếu app đang mở khi mã nguồn được cập nhật, lưu các chỉnh sửa rồi đóng và mở
lại để thấy phiên bản mới. Tên app là **Testbox Studio**; tên feature, file dữ
liệu và workflow vẫn thể hiện đúng chức năng Gradebook hiện đang hỗ trợ.

## Chuẩn bị trước khi bấm Run

1. Mở **Docker Desktop**, chờ Docker Engine chạy. Sau đó mở PowerShell tại
   thư mục Pro3 và bật container Moodle đã có:

   ```powershell
   docker start pro2-moodle
   .\.venv\Scripts\python.exe tools/wait_for_moodle.py
   ```

   Chờ dòng `Moodle ready: HTTP 200`. Testbox Studio không tự bật Docker Desktop
   hoặc container khi bấm Run. Nếu báo `ERR_CONNECTION_REFUSED`, kiểm tra lại
   Docker, container và URL Moodle trước khi chạy tiếp.
2. Mở `http://127.0.0.1:9501/login/index.php`, kiểm tra tài khoản teacher có
   quyền sửa Gradebook của Course 1, ID `2`. Fixture hiện tại dùng
   `teacher01` / `1234`; cập nhật Run configuration nếu bạn đã đổi tài khoản.
3. Kiểm tra Moodle dùng English UI, Minimum grade được bật, Natural aggregation
   và scale cần thiết đã tồn tại; xem **Moodle preconditions** bên dưới.
4. Trong app, chọn Functional, Level 1 hoặc Level 2, Chrome và bật
   **Headless (background)** cho lần kiểm tra đầu. URL là
   `http://127.0.0.1:9501`, Course ID là `2`. Chạy một case trước khi chạy cả bộ.
5. Đối chiếu **Test data** với **JSON / Expected**, rồi Apply changes. Ví dụ,
   TC-003-001 gốc nhập Grade type `Value` và kỳ vọng lưu `Value`. Nếu đổi input
   sang `Text` trong khi Expected vẫn là `Value`, case sẽ FAIL đúng theo phép
   so sánh. Khi thiết kế case Text mới, cần xác định lại expected fields và
   trạng thái điều khiển phù hợp; không tự đổi Expected chỉ để làm mất FAIL.
6. Chạy tuần tự, tránh sửa cùng course khi automation đang chạy. Theo dõi
   Execution và Open results để phân biệt ERROR kết nối với FAIL assertion.

Python/Selenium trên máy hiện tại đã được cài sẵn. Internet có thể cần khi
Selenium Manager tải driver phù hợp sau khi browser cập nhật. Opera GX còn cần
Chromium version phù hợp trong site settings; nên xác nhận Chrome hoạt động
trước, rồi mới chọn Opera GX.

## Project 3 — Feature 003: Gradebook — Bùi Quốc Thái

Python 3.12 + Selenium WebDriver + unittest. This submission implements the
36 manual grade-item cases from Project 2 as data-driven automation.

**Gradebook dataset verification: completed on 23 November 2026.**
Level 1 and Level 2 each have 35 PASS and 1 FAIL: TC-003-036 reproduces the
known Moodle defect F003-D01. Chrome/Edge compatibility passed 10/10, and
supplementary Opera GX coverage passed 5/5. See **Verification results** below
for the report files and the retained history of one infrastructure recheck.

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
- **Steps:** editable actions for workflow `steps`; a generated read-only preview
  remains available for legacy Gradebook workflows.
- **JSON / Expected:** edit extra input options and expected assertions
  independently. Changing an input never silently changes its expected value.
- **Source:** original Excel preconditions, notes, defect reference and manual
  steps. Imported manual steps are reference material; the Steps tab reflects
  the current executable Gradebook workflow.
- **Run configuration:** Level 1/2, Chrome/Edge/both, site/course, credentials,
  site JSON and functional/compatibility mode.
  Opera GX is also available as an experimental Chromium adapter. Headless
  mode is enabled by default so runs can continue while other applications
  occupy the display. Compatibility mode runs Chrome and Edge in the selected
  headless/windowed mode.
- **Execution:** live action events, per-case results and links to the actual
  output folder. Browser tests only start when **Run** is pressed. **Stop after
  case** finishes the active case and its cleanup rather than killing a browser.

The existing Gradebook workspace is seeded with the 36 source cases grouped into five
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

The original Project 2 workbook has an explicit Gradebook adapter in the import
wizard. Its `003 - Moodle Grading` sheet is converted with the CLI extractor.
Other spreadsheet layouts can be mapped to executable steps or datasets.
Excel formulas are not supported as XLSX test inputs; exported values are
literal text, including strings that start with `=`.

New cases default to the general `steps` workflow. Five Gradebook templates
remain available. Recording, conditional steps, loops and advanced playback
are still on the development roadmap; they are not claimed as complete.

Run uses an immutable snapshot (CSV data and, for editable tests, JSON steps)
of the selected folders/cases, so edits do not alter that invocation. Compatibility
mode always uses Level 2, both browsers, and the original fixed five case IDs.
Run-configuration passwords are supplied to the child process environment and
are not saved in workspace JSON. Test data entered explicitly in datasets is
part of that saved dataset. A stopped/incomplete run is not reported as successful.

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
startup/visual inspection. These were the initial offline checks; browser
execution is recorded separately below and in its actual result files.

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
  browser.py                     Chrome/Edge/Opera creation
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

`execution_status_at_extraction: NOT RUN` in the source manifest records the
initial extraction stage. Later Python execution outcomes are stored in the
verification reports separately.

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

## Moodle preconditions

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

## VS Code, Docker and Opera GX

The prepared `.vscode/tasks.json` provides repeatable commands through
**Terminal → Run Task** (or **Tasks: Run Task** in the Command Palette):

- `Testbox: smoke Level 2 (Chrome)` runs TC-003-011.
- `Testbox: all Level 1 (Chrome)` and `Testbox: all Level 2 (Chrome)` each run
  the entire 36-row dataset.
- `Testbox: compatibility (Chrome + Edge)` runs the fixed ten executions.
- `Testbox: smoke Opera GX (headless)` runs the same smoke case with GX.
- `Testbox: open desktop app` opens the editor without starting any tests.

The test tasks use `--headless --reuse-browser`, first start the existing `pro2-moodle` container and wait for
its HTTP login page. Docker Desktop must already be running and the Project 2
container/fixture must already exist. These tasks do not install or reset
Moodle. Python and Docker extensions can help inspect the environment, while
the actual test assertions run in the Python/unittest process.

Run the suites sequentially against Course 1; each suite records baseline item
IDs and checks cleanup. Browser sessions use fresh profiles rather than the
user's normal Chrome, Edge or Opera profile. With `--reuse-browser`, one profile
per browser is reused for the suite, while cookies and web storage are cleared
before each case. Every case still authenticates and checks its own data and
cleanup. This avoids repeated browser startup/shutdown overhead.

Headless sessions use a fixed 1440 × 900 CSS viewport and device scale factor
1. No browser window needs to stay visible or compete with another fullscreen
application. WebDriver commands have a 60-second transport limit in addition
to page/element waits. Browser teardown closes the owned temporary browser
through its debugging connection before stopping its driver service.

Opera GX 139.0.6053.63 on the inspected machine embeds Chromium
155.0.8059.85. The Opera adapter therefore uses ChromeDriver for Chromium 155,
not a driver chosen from the Opera product version. The current site settings
contain `opera_chromium_version: "155"`. Update that setting after a GX engine
update. The default binary location is the Windows per-user Opera GX install;
override it with `opera_binary` in site JSON or `TESTBOX_OPERA_BINARY`.
`TESTBOX_OPERA_CHROMIUM_VERSION` overrides the configured engine version.

Example of an explicit GX run:

```powershell
.\.venv\Scripts\python.exe -m level2.test_gradebook --browser opera --headless --reuse-browser --cases TC-003-011
```

The result records both the requested browser and its actual user agent, so
Opera sessions must identify themselves with `OPR/`. GX is supplementary
coverage; it does not replace either browser in NF-003-COMPAT.

Browser navigation uses the `eager` strategy plus explicit waits for actual
controls and persisted state. Input values are read back before submission.
Selenium's temporary profiles disable password saving and password-leak
prompts. This is scoped to automated browser sessions; the user's normal
browser profile and Moodle passwords are not changed. During the first
exploratory run, Chrome's native "Change your password" warning intercepted
mouse/keyboard input. That run was stopped after cleanup and is excluded
from final verification.

Final verification uses native WebDriver text/click actions with interaction
fallbacks disabled. A blocked native action is an error, not silently bypassed.
An optional `allow_interaction_fallbacks` setting exists for diagnostics only;
when explicitly enabled, CDP text and DOM click fallbacks are logged. Such a
diagnostic run is not used to establish native interaction compatibility.

## Installation

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
require Selenium. The commands below start browser execution explicitly.

## Level 1

```powershell
.\.venv\Scripts\python.exe -m level1.test_gradebook --headless --reuse-browser
```

This runs all 36 CSV cases on Chrome, using URLs and locators from
`level1/settings.py`.

Example of selecting one case:

```powershell
.\.venv\Scripts\python.exe -m level1.test_gradebook --cases TC-003-011
```

## Level 2

```powershell
.\.venv\Scripts\python.exe -m level2.test_gradebook --headless --reuse-browser
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

Each case gets a teacher login and independent setup/cleanup. Without
`--reuse-browser`, each case also gets a fresh browser profile. The desktop
Gradebook app runs and VS Code tasks reuse a suite profile with per-case
cookies/storage reset. Editable-step app runs currently use a fresh profile per
data row; the general CLI also offers explicit `--reuse-browser`. Verification
can run headless at 1440 × 900; mode, actual viewport,
device scale and session-isolation policy are recorded in results.

## Non-functional requirement NF-003-COMPAT

Requirement: the selected Gradebook workflows work on **Chrome and Edge**
at 1440 × 900, with the necessary controls visible and operable.

Run:

```powershell
.\.venv\Scripts\python.exe -m nonfunctional.compatibility --headless --reuse-browser
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
known defect. Project 3 browser execution has reproduced this defect in both
levels. See the verification results below and the
[captured error page](artifacts/F003-D01-maximum-empty.png). Project 2 outcomes
are reference material, separate from these new Python executions.

## Verification results

Verified on **23 November 2026**, against the existing `pro2-moodle` Docker
fixture: Moodle 5.1.8, Course 1 / ID 2, English UI and Asia/Bangkok timezone.
All final runs used `--headless --reuse-browser`, a 1440 × 900 CSS viewport,
device scale 1, and native WebDriver text/click/select actions with diagnostic
interaction fallbacks disabled.

| Suite | Browser | Executions | PASS | FAIL | ERROR / SKIP |
| --- | --- | ---: | ---: | ---: | ---: |
| Level 1 | Chrome 157.0.8103.79 | 36 | 35 | 1 | 0 / 0 |
| Level 2 | Chrome 157.0.8103.79 | 36 | 35 | 1 | 0 / 0 |
| NF-003-COMPAT | Chrome 157 + Edge 158.0.4370.33 | 10 | 10 | 0 | 0 / 0 |
| Supplementary GX sample | Opera GX / Chromium 155.0.8059.85 | 5 | 5 | 0 | 0 / 0 |

The two FAIL executions are TC-003-036 in the two levels. Both captured
**Error writing to database** instead of the expected inline numeric message.
The functional runners therefore correctly returned exit code 1; the
compatibility and Opera runners returned 0.

These are **87 unique planned executions**, with **88 total attempts**.
Level 1 TC-003-005 initially recorded ERROR when the post-click check referenced
a document already replaced by login navigation. The helper now recognizes
that specific detached-document response and continues checking the resulting
page. A targeted rerun passed; its original ERROR and subsequent PASS are both
retained in `retry_history`. The table uses the latest outcome per case/browser.
Level 2 ran all 36 cases with the corrected helper.

Every final case completed cleanup. A separate read-only Moodle audit confirmed
that manual grade items returned to the original baseline: **0 before, 0 after**.
No diagnostic interaction fallback events occurred.

- [Verification summary, environment, failures and retry history](artifacts/verification-summary.json)
- [Consolidated case results for Excel](artifacts/verification-cases.csv)
- [F003-D01 screenshot](artifacts/F003-D01-maximum-empty.png)

Full raw reports, traces and evidence remain locally in `results/final-headless/`;
live logs are `results/final-headless-*-live.log`. Earlier exploratory and
interrupted windowed runs are outside this final run directory. To regenerate
the consolidated files from these retained local outputs and environment audits:

```powershell
.\.venv\Scripts\python.exe tools/summarize_verification.py
```

## Execution outputs

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
running the tests; local raw results are retained under `results/`.

## AI usage record for the eventual report

AI assistance was used to inspect the Project 2 workbook and Recorder,
design the data mapping, extract CSV data, and write/review the Python
automation, desktop app, file exchange and documentation. The tool was OpenAI Codex in this conversation.
Initial preparation did not execute browser tests; subsequent verification
and its automation fixes are recorded in the execution results. Use the actual prompts
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
- [VS Code task configuration](https://code.visualstudio.com/docs/debugtest/tasks)
- [ChromeDriver version selection](https://developer.chrome.com/docs/chromedriver/downloads/version-selection)
- [Opera's Chromium WebDriver project](https://github.com/operasoftware/operachromiumdriver)
