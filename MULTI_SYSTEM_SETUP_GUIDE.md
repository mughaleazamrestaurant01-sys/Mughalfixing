# Mughal-E-Azam POS: Multi-System Setup Guide (A–Z)

> **Use this document later when the restaurant is ready to run a second POS
> terminal.** It documents the currently implemented **basic LAN mode** and the
> production work still required for simultaneous multi-user operation.

## 1. Current implementation and safety limit

The current application can run one main counter installation as an authenticated
LAN data host and can run the laptop as a client of that host. Both installations
then use the counter computer's operational POS data. Receipt and kitchen printer
settings remain local to each computer.

This is **not yet a production-safe simultaneous two-user system**. It does not
implement live screen synchronization, server-side table locks, or transactional
per-order stock/invoice handling. Until the PostgreSQL/server upgrade in section 14
is built, use it only for testing or with one operator making changes at a time.

## 2. Equipment checklist

- Main counter PC: Windows 10, wired Ethernet, always on during laptop use.
- Laptop: Windows 11, wired Ethernet when possible.
- Kitchen printer: XSP-210, LAN IP reserved as `192.168.10.220`.
- Counter receipt printer: Star TSP700II / TSP743II, USB.
- Laptop receipt printer: SRP-352 Plus, USB.
- Both PCs and the printer connected to the same trusted router/LAN.

## 3. Reserve device addresses

1. In the router, reserve the XSP-210 DHCP address as `192.168.10.220`.
2. Reserve a stable LAN address for the counter PC, for example
   `192.168.10.10`.
3. On the counter PC, run `ipconfig` and record the Ethernet IPv4 address.
4. From the laptop, run `ping <counter-ip>` and `ping 192.168.10.220`.
   Resolve cabling, router, or Windows network-profile issues before proceeding.

## 4. Install Windows printer queues

### Counter PC

1. Install the Star USB driver and verify a Windows test print.
2. Add the XSP-210 manually as a **TCP/IP printer** using `192.168.10.220`.
3. Install the XSP-210 driver and name the queue `Kitchen XSP-210`.

### Laptop

1. Install the SRP-352 Plus USB driver and verify a Windows test print.
2. Add the same XSP-210 TCP/IP printer at `192.168.10.220`.
3. Install the XSP-210 driver and name the queue `Kitchen XSP-210`.

## 5. Install the updated POS executable

1. Build or download the same current **single-file** POS EXE for both computers.
   The release artifact is `Mughal-E-Azam-POS.exe`; do not use an older package
   that includes an `_internal` folder.
2. Replace old EXEs; keep a stable path such as
   `C:\MughalPOS\MughalEAzamPOS.exe`.
3. Use the normal EXE without LAN arguments for single-PC operation.
4. Use the special shortcuts below only when testing the multi-system mode.

## 6. Create a shared LAN secret

Create one long private secret, for example:

```text
MughalPOS-Change-This-To-A-Long-Random-Private-Secret-2026
```

- Keep it private and use the exact same value on both PCs.
- Do not use a short password, and do not expose the server to the internet.

## 7. Create the main-counter server shortcut

On the **counter PC**, create a Desktop shortcut with this Target. Replace the EXE
path and secret with your real values:

```bat
"C:\MughalPOS\MughalEAzamPOS.exe" --share-lan --server-token "MughalPOS-Change-This-To-A-Long-Random-Private-Secret-2026"
```

Name it **Mughal POS — Main Counter Server**. Start the counter application with
this shortcut before starting the laptop. The shared server listens on TCP port
`8765` by default.

## 8. Allow only the restaurant LAN through Windows Firewall

On the counter PC, open **Command Prompt as Administrator** and run:

```bat
netsh advfirewall firewall add rule name="Mughal POS Shared LAN" dir=in action=allow protocol=TCP localport=8765 profile=private
```

Do not create an internet router port-forward for this service. Keep the Windows
network profile set to **Private**.

## 9. Create the laptop client shortcut

On the laptop, create a Desktop shortcut. Replace `192.168.10.10` with the counter
PC's actual reserved address and use the same secret:

```bat
"C:\MughalPOS\MughalEAzamPOS.exe" --server-url "http://192.168.10.10:8765" --server-token "MughalPOS-Change-This-To-A-Long-Random-Private-Secret-2026"
```

Name it **Mughal POS — Laptop Client**. Do not start the laptop with the normal
shortcut when testing shared mode, because the normal shortcut opens a separate
local database.

## 10. Configure POS printers separately

### Counter PC POS settings

- Receipt printer: `Counter Star Receipt Printer` (or the installed Star queue).
- Kitchen Ticket Printer: `Kitchen XSP-210`.

### Laptop POS settings

- Receipt printer: `Laptop SRP-352 Receipt Printer` (or the installed SRP queue).
- Kitchen Ticket Printer: `Kitchen XSP-210`.

Save the settings and run printer tests from each POS. These settings are local to
each terminal, so the laptop cannot replace the counter PC's receipt-printer choice.

### Counter receipt cutter diagnosis

For the installed **Star TSP700II (TSP743II)** queue, select **Windows Star driver**
in POS Hardware setup. This sends a driver-rendered job, so the driver’s configured
**Document Bottom: Partial Cut** setting can cut the receipt. The direct Star and
ESC/POS options are RAW jobs that bypass this driver feature. If the driver mode
does not cut, do this before changing the POS again:

1. Confirm the exact counter printer model has an auto-cutter fitted; a tear-bar
   model cannot be made to cut by software.
2. Turn the printer off, clear any paper/cover/cutter error, reload paper correctly,
   then turn it back on. Run the printer's own self-test or the Star utility's
   cutter test. If that test does not cut, the problem is the printer/cutter and
   requires driver/service support rather than a POS change.
3. In Windows **Settings → Bluetooth & devices → Printers & scanners → [Star
   printer] → Printer properties**, verify the queue uses the Star driver and the
   correct active USB port. In **Device Settings**, keep **Document Bottom** set to
   **Partial Cut** (as shown in the supplied working configuration).
4. Save **Windows Star driver** in the POS, then use **Test Receipt**. Use RAW
   profiles only when intentionally matching a printer's Star/line-mode or ESC/POS
   command emulation; those modes do not use the Windows driver’s Document Bottom
   setting.

## 11. Create users and permissions

Create users from the counter/admin account. Suggested accounts:

| Account | Typical access |
| --- | --- |
| Admin | All configuration, users, reports, inventory, backups, POS |
| Counter cashier | POS, tables, payments, receipts, Kitchen KOT |
| Delivery cashier | Takeaway/delivery POS, customers, payments, receipts, Kitchen KOT |
| Kitchen user | KDS only, if configured |

Give staff only the permissions required for their job. Do not share the admin
password with cashiers.

## 12. Acceptance testing

1. Start **Main Counter Server** on the counter PC.
2. Start **Laptop Client** on the laptop.
3. Log in with the correct user on each machine.
4. Verify a counter receipt prints to the Star printer only.
5. Verify a laptop receipt prints to the SRP-352 Plus only.
6. From each machine, click **Kitchen KOT** for a test order and verify output on
   the XSP-210.
7. Verify provisional bills and payment completion do not create an unrequested KOT.
8. Verify backup creation on the counter PC.
9. For the current basic mode, close/reopen the second client before checking a
   change made by the other one; live refresh is not yet implemented.

## 13. Current-operation rules and troubleshooting

- Keep the counter PC running, awake, and connected while the laptop is in use.
- Use only one PC at a time for edits until the production upgrade is completed.
- If the laptop cannot connect, check: counter POS is running in server mode,
  counter IP address, identical secret, `ping`, and the port-8765 firewall rule.
- Make and verify backups from the counter PC. Restore is a counter-PC operation.
- Do not put `database.sqlite` on a Windows shared folder or network drive.

## 14. Required production upgrade before simultaneous live operation

Build this before using both operators concurrently:

1. PostgreSQL database on the main counter/server PC.
2. A proper authenticated POS API service.
3. Normalized tables for users, roles/permissions, orders, order items, stock,
   tables, KDS tickets, customers, purchases, and expenses.
4. Server-side permission checks for every protected operation.
5. Database transactions for invoice numbering, order completion, stock deduction,
   table reservation/release, KDS state changes, and user edits.
6. WebSocket updates or safe polling so both screens refresh quickly.
7. Conflict handling and offline/reconnect status.
8. Simultaneous two-PC acceptance testing covering stock, tables, delivery, KOT,
   receipts, restart/reconnect, backup, and recovery.

Only after those items are complete should the restaurant run counter and laptop
operators simultaneously as a full shared POS system.
