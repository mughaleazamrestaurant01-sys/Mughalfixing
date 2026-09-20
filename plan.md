# POS hardening and completion plan

## 2026-09-18 emergency launch recovery — completed

- The loopback/WebView change did not work on the installed Windows runtime: the
  page remains at “Opening saved POS data” and the process-level mutex prevents a
  recovery launch even when no usable window exists. Replace both mechanisms with
  the known-compatible bundled `index.html` launch path, a bridge polling/retry
  bootstrap, and no stale-process launch block.
- The loopback server and launch-time mutex have now been removed from the startup
  path. The Vue bootstrap polls for the native bridge (so it cannot miss an early
  ready event), times out failed bridge/database calls, and presents a Retry
  connection control instead of holding the user on an unrecoverable overlay.
- Python compilation, inline Vue syntax, startup-path assertions, and whitespace
  validation have passed. Rebuild and replace the Windows EXE before testing on
  the counter PC; an existing installed EXE cannot contain this recovery change.

## 2026-09-18 receipt legibility and startup reliability — completed

- The on-site print photograph shows that the first template pass is reaching the
  printer, but it leaves blank header lines and still uses a dense, hard-to-read
  raw-text presentation. This pass will use a single high-contrast, centered
  fixed-width layout without empty address/phone rows and will preserve every
  receipt field.
- Desktop startup now uses a local threaded loopback asset endpoint on an
  operating-system-assigned port, verifies its serving thread before creating the
  WebView, and shuts it down with the application. This avoids intermittent
  `file://` WebView-origin startup failures and removes fixed-port conflicts.
- Native receipt composition now omits empty optional header rows and wraps long
  titles, addresses, and footers rather than truncating them, so the restaurant
  identity and receipt data remain centered, visible, and complete.
- The local asset endpoint and native receipt wrapping behaviour were checked in
  isolation; Python compilation, inline Vue syntax validation, and diff checks
  also pass.

## 2026-09-18 receipt-template implementation — completed

- Applying the five approved layouts in `Receipts design.html` to the live POS
  receipt pipeline: Kitchen KOT, unpaid preview bill, paid dine-in receipt,
  takeaway receipt, and delivery receipt. This includes both the on-screen
  printable document and the native thermal-printer text payload.
- The on-screen printable area now uses the approved monospace dividers,
  headings, order-type metadata, totals, and order-specific closing messages.
- The native thermal payload now mirrors those templates, including the KOT item
  grid, unpaid preview notice, paid/order-type totals, takeaway token, and
  delivery customer/COD sections. Python compilation, Vue script syntax, and
  mocked native print-payload checks for all five variants passed.

## Review status: single-computer POS completed; shared two-computer POS not yet built

This document was reviewed against the active desktop entry point (`index.html`) and
the native Python bridge (`app.py`). The stale observations in the previous version
have been replaced with the current implementation status.

## Delivered functionality

1. **One active application path.** The desktop application serves `index.html` and
   packages that file plus `assets/`. There is no second shipped HTML screen to
   maintain.
2. **Durable POS state.** SQLite persists menu items, inventory, recipes, orders,
   purchases, customers, tables, KDS tickets, carts, selected tables, printer
   configuration, the next order number, discounts, payment details, and unfinished
   customer/delivery fields. A watched, debounced save covers values changed directly
   in the screen, so they do not depend on a separate Save button. Reloading restores
   unfinished work and active kitchen tickets.
3. **Reliable order numbering.** The current order number is saved with the rest of
   the state, so normal application restarts do not return invoice numbering to
   `1001`.
4. **Recipe stock control.** Paid orders validate every recipe ingredient before
   completion. They are rejected when an ingredient is missing or stock is too low;
   otherwise the required quantities are deducted and persisted.
5. **Native receipt and KOT output.** The bridge renders configured receipt header
   and footer, order details, customer/table details, all line items, subtotal,
   discount, delivery fee, and total as raw thermal-printer text. Receipt printing,
   KOT printing, provisional bills, and historical reprints all use that payload.
6. **Account security and setup.** Passwords use PBKDF2 hashes, authentication is
   performed by the native bridge, and only non-sensitive user fields reach the UI.
   A new installation remains locked until its first administrator account is
   created. The last user cannot be deleted, and the last administrator cannot be
   deleted or demoted. The interface now uses the selected permission checkboxes to
   hide protected tabs/actions and rejects direct in-app attempts to use protected
   menu, inventory, table, KDS, or recipe-management actions.
7. **Safe startup and feedback.** The UI waits for the pywebview bridge before it
   reads data or unlocks the POS. Startup failures keep the application locked and
   display an error. Toast messages give users success and error feedback.
8. **Backups and restore.** Selecting a custom folder immediately creates a
   consistent SQLite backup there and stores that folder for future automatic
   backups. The Backup page also has an explicit **Create Backup Now** button and
   shows the saved file path or any backup error. Native backups include users; JSON
   export/import covers operational business state (but not user accounts). Restore
   validates a SQLite backup before replacing the live database.
9. **Payment validation.** Cash orders cannot be completed until cash received is
   at least the payable total. This prevents recording an underpaid cash sale.

## Validation completed

- Python source compilation and AST parsing succeeded.
- The inline Vue application script passed JavaScript syntax validation.
- Isolated SQLite tests verified administrator creation, password authentication,
  prevention of the final-administrator demotion/deletion, and deletion once a
  second administrator exists.
- State persistence and custom-folder backup were tested with a temporary SQLite
  database, including reopening the resulting backup and checking saved cart and
  discount data.
- Permission-gate checks verified that menu management requires `menu_manage` (not
  merely `pos`) and that protected action methods have an explicit permission guard.
- A whitespace check found no patch errors.

## Confirmed restaurant setup and requirements

The requested installation is a **two-computer shared POS** on an existing wired
Ethernet LAN. Mobile ordering is deliberately out of scope for now.

| Device | Operating system | Required use | Local receipt printer |
| --- | --- | --- | --- |
| Main counter PC | Windows 10 | Runs all day; central server, dine-in/counter POS, administration, reports | Star TSP700II / TSP743II (USB) |
| Evening laptop | Windows 11 | Takeaway and delivery POS from 6 PM to 11 PM | SRP-352 Plus (USB) |
| Kitchen printer | Network-connected | Prints KOT only after the user clicks **Kitchen KOT** | XSP-210 (LAN; reserved IP `192.168.10.220`) |

Both computers and the kitchen printer are already connected to the same router by
Ethernet. The administrator will create the laptop user's account and choose its
permissions inside the POS.

### Required shared behaviour

1. Both computers must read and write one shared set of users, menu, recipes,
   stock, customers, orders, invoices, reports, KDS tickets, and tables.
2. A table made busy on either computer must become busy on the other computer
   promptly, before it can be selected for another order.
3. A takeaway/delivery order entered on the laptop must promptly appear on the main
   counter PC, including sales, customer, inventory, and history data.
4. The main PC prints customer receipts only to its Star USB printer; the laptop
   prints customer receipts only to its SRP-352 Plus USB printer.
5. Both PCs must be able to send a KOT to the same kitchen network printer, but
   only after the operator explicitly clicks the **Kitchen KOT** button. Completing
   payment and printing a provisional bill must not create a KOT.
6. The main counter PC must stay powered on while the laptop is in use. Internet is
   not required for this local-LAN system.

## Shared two-computer feature: current progress

**Implementation progress: basic shared mode is implemented.** The main counter can
serve its own local SQLite database through an authenticated LAN HTTP gateway, and
the laptop can use that gateway instead of creating a second operational database.
Both PCs therefore use the counter PC's users, menu, stock, orders, tables, KDS
queue, reports, and customers. Receipt/KOT printer discovery and printing remain
local to each PC.

Run the main counter application with `--share-lan --server-token <long-secret>`.
Run the laptop with `--server-url http://<counter-LAN-IP>:8765 --server-token
<same-long-secret>`. Permit inbound TCP 8765 only from the restaurant LAN in the
counter PC's Windows Firewall. The token must be a long private value and must not
be reused outside this restaurant. Do not share the SQLite file through a Windows
folder or network drive: SQLite over a network share is not safe for simultaneous
POS use.

### Build plan before the laptop is connected

1. **Central server and database:** run a proper server service on the main counter
   PC and move shared operational data to PostgreSQL (recommended) or another
   supported network database. The service must bind only to the restaurant LAN and
   require authenticated requests.
2. **Desktop client mode:** make both POS installations connect to that server rather
   than opening their own local SQLite operational database. Keep each PC's printer
   selection local to that PC.
3. **Safe transactions:** make order creation, recipe deduction, invoice numbering,
   table status, KDS changes, and user edits atomic on the server so two operators
   cannot overwrite each other or sell the same stock twice.
4. **Live synchronisation:** add server-driven updates or short safe polling so the
   other screen sees table/KDS/order changes promptly. Include reconnect and offline
   messages; do not silently save an offline laptop order to a different local
   database.
5. **Kitchen printer installation:** reserve a fixed DHCP address for the XSP-210 in
   the router, install its Windows network/TCP-IP queue on both PCs, then select
   that queue as the kitchen printer on each PC. Use its confirmed reserved IP
   `192.168.10.220` and the XSP-210 driver when creating the TCP/IP queue on both PCs.
6. **End-to-end acceptance test:** use both PCs at the same time to test busy-table
   blocking, laptop delivery orders, KOT-only printing from each PC, each local
   receipt printer, stock deduction, simultaneous saves, restart/reconnect, backup,
   and recovery.

## Remaining operational considerations

These are not placeholder or dummy features, but are sensible future enhancements:

1. **CSV parser scope.** CSV import is designed for simple one-line records. It
   does not yet fully support escaped quotation marks or multiline quoted fields.
2. **Printing depends on operating-system setup.** The app lists installed Windows
   or CUPS queues. A physical printer must have an installed driver/queue before it
   can be selected, and printer hardware/driver settings determine any required
   post-receipt paper feed.
3. **JSON backups intentionally exclude accounts.** Use the native SQLite folder
   backup whenever user accounts must be moved or recovered too.
4. **Shared-POS dependency.** The two-computer feature must be built and tested
   before the laptop is used as a live second terminal. Until then, it remains a
   separate local POS installation and must not be treated as synchronized.

## Maintainer attention for future chats

Treat all single-computer functionality above as complete unless a reproducible bug
is reported. The only planned product work requiring major development is the shared
two-computer/server feature described in this document. Before starting that work,
confirm the kitchen printer's fixed LAN IP address and agree on the server database
and installation process. Do not claim that the two PCs are synchronized, and do not
use a network-shared SQLite file as a shortcut. When adding a new screen or action,
assign it to an existing permission and enforce that permission both in the visible
UI and in its action method.

## 2026-09-18 reliability work in progress

- The reported generic “Unable to save POS data” notification is being addressed by
  returning a concrete SQLite/serialization error from the bridge instead of letting
  an exception become an opaque failed webview call.
- Automatic folder backups are now rate-limited to once per minute. The previous
  implementation made a full SQLite backup after every persisted UI update, which
  could block the POS noticeably as order history grew. Explicit backup creation and
  the first backup after choosing a folder remain immediate.
- The shared two-computer feature is being implemented as an authenticated LAN API;
  it will keep receipt-printer configuration local on each Windows computer while
  operational POS data is owned by the main counter computer. A Windows network
  share of SQLite remains unsupported.
- A first usable LAN implementation is now present: start the counter application
  with `--share-lan --server-token <long-secret>` and start the laptop with
  `--server-url http://<counter-LAN-IP>:8765 --server-token <same-long-secret>`.
  The laptop reads/writes the counter's database over an authenticated HTTP bridge,
  while printer discovery and printing still occur on the laptop itself. The
  implementation serializes database writes but is not yet a replacement for
  purpose-built per-order transactional APIs; operators must not edit the same
  unfinished order simultaneously.
- Printer configuration is intentionally terminal-local: it is stored in each
  installation's settings database and excluded from the shared operational state,
  so laptop receipt/KOT choices cannot replace the counter PC's printer queues.
- Save requests are now coalesced in the UI (700 ms debounce) rather than being
  sent both by every action and by the deep state watcher. Automatic backup work
  also runs after the SQLite write on a background thread, so a large backup cannot
  hold the POS screen while it is saving an order.
- The state bridge rejects malformed payloads with a descriptive result and the UI
  displays a rejected bridge error message, making the next on-site failure
  diagnosable rather than showing only the generic save toast.
- The coalescing delay is set to 700 ms: frequent cart quantity changes and delivery
  field edits are persisted as one final snapshot after the operator pauses, while
  all normal order changes remain automatically saved.
- Startup now unlocks the POS as soon as saved data is available. Printer enumeration
  proceeds in the background because Windows can pause while probing unavailable
  network printers; a printer scan no longer keeps the entire application on its
  opening screen.
- Added `MULTI_SYSTEM_SETUP_GUIDE.md`, a deferred A–Z deployment guide for the
  basic LAN mode, local printer setup, access control, validation, troubleshooting,
  and the required PostgreSQL/server upgrade before simultaneous live operation.
- Receipt and startup improvements are now being implemented following successful
  physical printer tests on the main counter PC: a professional, configurable
  customer receipt format; printer-specific cutter commands; and a review of the
  first-start database loading path. KOT output remains deliberately compact.
- Customer receipts now have dedicated configurable restaurant name, tagline,
  address, phone, professional footer, and counter-cutter profile settings. Printed
  receipt data includes order type, payment method, customer details, and delivery
  address when supplied; KOTs intentionally remain simple and use their existing
  ESC/POS cutter path.
- The on-screen printable preview now mirrors the professional customer receipt
  layout (restaurant identity, order type, contact/delivery details, and premium
  footer), so Preview Bill and the printed bill have the same non-generic content.

## Single-main-computer release readiness — 2026-09-18

### Reported release blockers — resolved

- The Windows workflow now uses PyInstaller `--onefile` and uploads only
  `Mughal-E-Azam-POS.exe`. The previous `--onedir` release required its `_internal`
  runtime directory and therefore failed with a missing `python311.dll` after that
  directory was deleted. The replacement release is a portable EXE; operators must
  delete the old EXE and `_internal` folder, then download the new artifact.
- Counter receipts and printer tests now feed five lines before the selected cutter
  command. Hardware setup offers Star TSP700II/TSP743II full/partial cut plus
  ESC/POS full/partial alternatives, allowing the command to match the active
  printer emulation. Existing saved `star` and `escpos` profile values remain
  compatible.

### Counter cutter follow-up — on-site verification required

- The previous receipt path used the Windows `RAW` datatype and appended selected
  cut bytes after a five-line feed. If every direct RAW profile prints the receipt
  but none cuts it, Windows has delivered the job and the remaining fault is at
  the selected queue's command emulation, the printer's cutter configuration, or
  the cutter hardware/paper path—not in receipt content. Verify the exact Star
  model includes an auto-cutter, run the Star utility/self-test cutter check,
  confirm the Windows queue uses the correct Star driver and USB port, then set
  the same Star/ESC-POS emulation in both the printer and POS before retesting.

### 2026-09-18 Star driver-cut integration — completed

- The supplied Windows screenshots confirm that the installed **Star TSP700II
  (TSP743II)** driver is configured for **Document Bottom: Partial Cut**, and that
  another application cuts successfully through this same queue. The previous POS
  path used a `RAW` Windows print job, which deliberately bypassed that driver feature.
  Counter receipts using the default **Windows Star driver** profile now render
  through the Windows/Star driver, allowing its confirmed Document Bottom setting
  to issue the cut. Raw Star and ESC/POS profiles remain available for queues
  configured for direct command control.

### 2026-09-18 desktop startup redesign — completed

- The desktop shell currently starts an unnecessary local HTTP asset server and
  then opens the embedded browser against it. This adds a second startup service,
  a socket bind, and a browser network request even though all assets are already
  packaged locally. The application now launches the bundled `index.html` directly
  in the WebView, without a local HTTP server, socket bind, or loopback request.
  A Windows single-instance guard prevents duplicate launches from contending for
  the same database, and the UI now reports a WebView bridge timeout after ten
  seconds rather than remaining on an indefinite loading screen.

### 2026-09-18 responsiveness pass — completed

- SQLite lock waits are limited to three seconds, and the WAL mode is only changed
  for older databases that need migration, avoiding an unnecessary write lock on
  every normal launch. The UI no longer deep-watches and traverses the complete
  operational history for each reactive change; direct-entry fields are watched
  individually while collection actions retain their debounced persistence calls.
  History and admin sales calculations are now skipped while their tabs are not
  displayed.
- The proposed binary `favicon.ico` replacement was reverted because the current
  pull-request system does not accept binary file diffs. The in-app logo already
  uses rounded corners and a yellow border; the Windows executable icon can be
  updated later through a binary-capable release channel without blocking code PRs.

The single-main-computer POS has been built and hardened through **2026-09-18** and
is **good to go** after the operator installs the current EXE and verifies the Star
receipt and XSP-210 KOT test prints. The confirmed main-PC configuration is: Star
TSP700II/TSP743II for customer receipts and XSP-210 at `192.168.10.220` for KOTs.

No routine code review or further feature work is required for the single-computer
installation unless the restaurant reports a reproducible problem or requests a new
feature. Keep the KOT simple, use the professional customer-receipt settings for
preview/final bills, and use the selected Star cutter mode after rebuilding this
release. The future proper PostgreSQL/live-sync project remains separate and must
be completed before simultaneous multi-terminal operation is approved.
- First-launch optimization now binds the local web server before WebView starts,
  uses a threaded local asset server, and configures SQLite's temporary store/cache
  for local POS reads. The Windows build has also changed from PyInstaller one-file
  extraction to a fast-start one-folder package; this avoids unpacking the entire
  application on every launch. Operators must replace the old EXE with the complete
  extracted `Mughal-E-Azam-POS` folder from the new build artifact.
- Further startup optimization removes automatic Windows printer enumeration from
  boot entirely; the administrator can scan printers from the dedicated Hardware
  setup screen when needed. Bundled CSS/JS/font/image assets now receive cache
  headers, so the embedded browser can reuse them on later launches instead of
  reloading every static resource.
- The local asset server also ignores harmless cancelled speculative browser asset
  requests, preventing a cancelled first-load request from producing a server error
  trace while the POS continues opening.
- Corrected the Windows distribution back to a single portable EXE after on-site
  feedback: the one-folder package's `_internal` folder is required and must never
  be deleted, so it was unsuitable for the requested simple installation. The live
  Admin → Hardware printer page now exposes the professional receipt fields and
  Star/ESC-POS cut-command selector directly (rather than only in an unused modal).
  Printer test jobs now use the selected counter cutter command.

## Update — window freezes when clicked right after opening (2026-09-19)

Reported behaviour: the POS opens, and if it is left alone for about 10 seconds it
starts working, but clicking anywhere in the window during those first seconds makes it
hang again. Fixes applied directly in this repository (same file layout, no refactor):

1. **Root cause — the browser-side Tailwind compiler.** `assets/js/tailwindcss.js`
   (Tailwind "Play CDN", 407 KB) compiled all CSS inside the WebView at launch and then
   re-compiled on every DOM change through a MutationObserver. Any click during that work
   queued input against a blocked UI thread, which Windows reports as "Not Responding".
   The stylesheet is now generated once into `assets/css/tailwind.css`
   (`tailwind.config.js`, `tailwind.src.css`, `build-css.cmd` / `build-css.sh`), the
   runtime compiler and its inline `tailwind.config` block were removed.
2. **Vue development build replaced** with the production build
   (`assets/js/vue.global.prod.js`, 167 KB instead of 594 KB) — same version, no warning
   and validation overhead on every render.
3. **WebView2 profile per process**: `_prepare_webview_runtime()` in `app.py` points
   WebView2 at `%APPDATA%\MughalEAzamPOS\webview2-sessions\<pid>`, so a read-only folder
   next to the EXE, or a previously hung POS process still holding the profile lock,
   cannot stop the new window from painting.
4. **Proxy-free WebView2 network**: `--no-proxy-server --no-first-run
   --disable-background-networking` so a WPAD/proxy setting cannot stall loopback asset
   loading part-way.
5. **Every data call is time-boxed** (20 s) and falls back to the native pywebview bridge
   if the loopback service is unreachable, then to a plain-language error; a stalled call
   can no longer freeze the interface.
6. **Backup folder is no longer a startup dependency** — it is fetched in the background
   after the login screen appears, and a bridge that lacks `get_backup_directory` is
   tolerated.
7. **No stale interface files**: the local asset server sends `Cache-Control: no-store`
   for HTML/JS and caches only fonts/images/CSS, so a rebuilt EXE never runs old scripts.
8. **Startup log**: every launch appends to `%APPDATA%\MughalEAzamPOS\startup.log`,
   including when the interface finishes loading in WebView2.

After adding `assets/css/tailwind.css` (and removing `tailwindcss.js` / `vue.global.js`),
the existing GitHub workflow builds the fixed EXE unchanged.

## Update — freeze on early clicks, printer selection, receipt design (2026-09-19)

Three counter-PC reports were addressed.

### 1. Window stops responding when clicked in the first seconds
* `_prepare_webview_runtime()` now reuses **one** WebView2 profile
  (`%APPDATA%\MughalEAzamPOS\webview2-profile`) instead of creating a new folder per
  launch. A new folder made every start a WebView2 "first run": the engine was still
  bootstrapping its profile while the window was already on screen, so a click in that
  window queued input against a browser process that could not accept it yet — Windows
  then painted the grey "Not Responding" frame. Old per-process folders are deleted.
  If the shared folder is not writable, a per-launch folder is used and logged.
* Windows launches now force the Edge WebView2 engine (`gui='edgechromium'`). The
  silent fallback to the legacy IE engine cannot run Vue 3 or `fetch()`, which looks
  identical to a frozen window. A missing runtime produces a readable message instead.
* The automatic backup no longer runs while staff are working with the till: nothing is
  copied in the first 60 s after launch and at most once every 5 minutes.

### 2. "Backup failed: WinError 32 … used by another process"
* Each backup writes a uniquely named temporary file (`pos_backup_<pid>_<time>.tmp`)
  instead of one fixed name, retries the final rename 6 times, and if the target file is
  still locked keeps a dated copy (`pos_backup_YYYYMMDD_HHMMSS.sqlite`) so no backup is
  lost. Leftover `.tmp` files from interrupted runs are swept automatically.

### 3. Printer selection was not saved
* The Hardware tab had no save path at all. Printer setup is now written as soon as it is
  changed (debounced deep watcher) and an explicit **Save Printer Setup** button was added.
* "Scan Printers" no longer overwrites a stored printer name with the first discovered
  queue; an offline queue that Windows does not list is kept and shown in the dropdown.

### 4. Printed receipts now follow "Receipts design.html"
* Receipt/KOT composition was rewritten as styled blocks (`_compose_receipt`), rendered
  two ways from one layout: real ESC/POS emphasis (`_render_escpos` — centring, bold,
  double-size restaurant name / TABLE / TOKEN / TOTAL lines) and the Windows Star driver
  path (`_print_with_windows_driver`, matching font weights and sizes, centred lines).
* `=`/`-` rules, `QTY DESCRIPTION / PRICE (RS.)` columns, INV/ORD, DATE, TABLE | SERVER,
  customer block, totals, CASH/CHANGE and the centred closing lines match the design file.

---

## Round 3 — Order history search, kitchen instructions, recipe search, branding on every ticket

### 1. Searchable order history with filters
* The History tab search box now matches bill number, customer, table, total, payment
  method, cashier, order status, kitchen instructions and item names.
* New filter controls: date (with an **All dates** button, previously the view was locked
  to a single day), payment method, cashier and order status — plus **Reset Filters** and a
  "showing X of Y records" counter.
* Payment-method and cashier options are derived from the saved records themselves
  (`historyPaymentMethods`, `historyCashiers`), so they always reflect real data.
* Every completed order now stores `cashierName` (from the signed-in user) and
  `status` (default `Completed`). Status can be changed per row from a dropdown
  (`setOrderStatus`: Completed / Refunded / Cancelled / On Hold) and is persisted.

### 2. Kitchen instructions field on the terminal
* A compact instructions box sits above the order action buttons in the cart panel
  (`orderInstructions`, 240 chars) with one-tap presets (Less spicy, Extra spicy,
  No onions, Serve first, Pack separately, Rush order) via `appendOrderInstruction`.
* The note travels with the KOT payload, the pre-bill, the final receipt and the KDS
  ticket, is saved on the order record (`orderNote`), shown in History, reprinted with
  the receipt, and cleared automatically after the order is completed.
* `_compose_receipt` prints it as a boxed `*** ORDER INSTRUCTIONS ***` section on the KOT
  and an `ORDER INSTRUCTIONS` section on the customer bill, wrapped to the paper width.

### 3. Recipe popup search
* The Recipe Rules modal gained a dish search field (name / code / category →
  `filteredRecipeDishes`) and an ingredient filter field.
* `recipeIngredientOptions(rec)` filters each ingredient dropdown by that search while
  always keeping the currently selected ingredient visible, so a rule never looks blank.
* "+ Add Ingredient Rule" now starts on the searched ingredient, warns when the inventory
  is empty instead of silently adding an invalid rule, and saves immediately.

### 4. Receipt Branding Customization now attaches to every document
* The kitchen ticket previously had no branding block at all — it now prints the custom
  restaurant name and tagline, plus the order date next to the time.
* The custom footer is appended to takeaway, delivery and preview documents too (it was
  only used for the plain dine-in receipt because their fixed closings overrode it).
* `date` and `serverName` are passed on every print payload (new orders, pre-bill, KOT and
  historical reprints), so reprints show the original date and the cashier who rang it.
