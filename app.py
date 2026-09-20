import json
import os
import hashlib
import hmac
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import argparse
import functools
import http.server
import time
import urllib.error
import urllib.request

import webview


_PROCESS_STARTED = time.monotonic()


def get_base_dir():
    return getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))


def _log_startup(message):
    """Append a timestamped launch line so a failed start can be diagnosed."""
    try:
        with open(os.path.join(get_data_dir(), 'startup.log'), 'a', encoding='utf-8') as handle:
            handle.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} [pid {os.getpid()}] {message}\n')
    except Exception:
        pass


def _prepare_webview_runtime():
    """Give WebView2 one stable, writable profile and a proxy-free network.

    A fresh profile folder per launch made every start a WebView2 "first run":
    the engine bootstraps its profile while the window is already visible, and a
    click during those few seconds queued input against a browser process that
    was not accepting it yet - the window then went grey/"Not Responding".
    One reused profile removes that first-run work from every launch.
    A stale lock from a crashed run is handled by falling back to a fresh folder.
    """
    if sys.platform != 'win32':
        return
    root = os.path.join(get_data_dir(), 'webview2-profile')
    try:
        os.makedirs(root, exist_ok=True)
        probe = os.path.join(root, 'pos-write-test')
        with open(probe, 'w', encoding='utf-8') as handle:
            handle.write('ok')
        os.unlink(probe)
        profile = root
    except Exception as exc:
        profile = os.path.join(get_data_dir(), 'webview2-profile-' + str(os.getpid()))
        os.makedirs(profile, exist_ok=True)
        _log_startup(f'reusable WebView2 profile unavailable ({exc}); using {profile}')
    os.environ['WEBVIEW2_USER_DATA_FOLDER'] = profile
    os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = (
        '--no-proxy-server --no-first-run --no-default-browser-check '
        '--disable-background-networking --disable-features=msWebOOUI,msPdfOOUI'
    )
    # Remove the per-process profiles written by earlier versions; they waste disk
    # and each one had to be bootstrapped from scratch.
    legacy = os.path.join(get_data_dir(), 'webview2-sessions')
    if os.path.isdir(legacy):
        shutil.rmtree(legacy, ignore_errors=True)
    _log_startup(f'WebView2 profile: {profile}')


def get_data_dir():
    """Keep operational data outside a PyInstaller bundle and uninstall folder."""
    root = os.environ.get('APPDATA') if sys.platform == 'win32' else os.path.expanduser('~/.local/share')
    path = os.path.join(root or os.path.expanduser('~'), 'MughalEAzamPOS')
    os.makedirs(path, exist_ok=True)
    return path


class LocalAssetServer:
    """Serve the bundled interface from a private, verified loopback address.

    Loading the POS from ``file://`` makes the WebView bridge dependent on the
    browser engine's local-file security policy.  That policy differs between
    installed Windows WebView runtimes and was the source of the startup screen
    becoming stuck.  A loopback-only server gives every runtime the same normal
    document origin without exposing the POS on the restaurant network.
    """

    def __init__(self, directory, api):
        handler = functools.partial(self._handler(), directory=directory)
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.server.daemon_threads = True
        self.server.api = api
        self.thread = threading.Thread(target=self.server.serve_forever, name='pos-assets', daemon=True)

    @staticmethod
    def _handler():
        class QuietAssetHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def _reply(self, status, payload):
                encoded = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def _payload(self):
                length = int(self.headers.get('Content-Length', 0))
                return json.loads(self.rfile.read(length).decode('utf-8')) if length else {}

            def _api_call(self, method, payload):
                api = self.server.api
                calls = {
                    'boot': lambda: api.get_boot_data(),
                    'printer-config': lambda: api.get_printer_config(),
                    'backup-directory': lambda: {'directory': api.get_backup_directory()},
                    'system-printers': lambda: api.get_system_printers(),
                    'save-state': lambda: api.save_state(payload.get('state', {})),
                    'save-printer-config': lambda: api.save_printer_config(payload.get('config', {})),
                    'authenticate': lambda: api.authenticate(payload.get('username'), payload.get('password')),
                    'save-user': lambda: api.save_user(payload.get('user', {}), payload.get('userId')),
                    'delete-user': lambda: api.delete_user(payload.get('userId')),
                    'print-direct': lambda: api.print_direct(payload.get('printerName'), payload.get('receiptData', {})),
                    'test-printer': lambda: api.test_printer(payload.get('printerName'), payload.get('receiptType', 'Test'), payload.get('cutMode', 'escpos_full'), payload.get('config', {})),
                    'create-backup': lambda: api.create_backup_now(),
                }
                if method not in calls:
                    raise ValueError('Unknown local POS API request.')
                return calls[method]()

            def end_headers(self):
                # Never let an old interface file stay cached against a newly built EXE.
                if not self.path.startswith('/api/'):
                    if self.path.lower().endswith(('.css', '.woff2', '.ttf', '.jpg', '.png', '.ico')):
                        self.send_header('Cache-Control', 'public, max-age=86400')
                    else:
                        self.send_header('Cache-Control', 'no-store')
                super().end_headers()

            def do_GET(self):
                if self.path.startswith('/api/'):
                    try:
                        self._reply(200, self._api_call(self.path[5:], {}))
                    except Exception as exc:
                        self._reply(500, {'ok': False, 'error': f'Local POS service error: {exc}'})
                    return
                super().do_GET()

            def do_POST(self):
                if not self.path.startswith('/api/'):
                    self.send_error(404)
                    return
                try:
                    self._reply(200, self._api_call(self.path[5:], self._payload()))
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    self._reply(400, {'ok': False, 'error': f'Invalid local POS request: {exc}'})
                except Exception as exc:
                    self._reply(500, {'ok': False, 'error': f'Local POS service error: {exc}'})

        return QuietAssetHandler

    @property
    def url(self):
        host, port = self.server.server_address[:2]
        return f'http://{host}:{port}/index.html'

    def start(self):
        self.thread.start()
        # The listening socket is created before the thread starts.  Verify the
        # actual entry document now, so a packaging/path problem is reported
        # before a WebView window is created.
        try:
            with urllib.request.urlopen(self.url, timeout=3) as response:
                if response.status != 200:
                    raise RuntimeError(f'asset server returned HTTP {response.status}')
        except Exception:
            self.close()
            raise

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        if self.thread.is_alive():
            self.thread.join(timeout=2)


class Api:
    def __init__(self, database_path):
        self.database_path = database_path
        self.window = None
        self._database_lock = threading.RLock()
        self._last_automatic_backup = 0.0
        self._backup_in_progress = False
        self._initialize_database()

    def _connection(self):
        # Do not leave the UI appearing frozen for ten seconds when a second
        # process or interrupted old instance has a database lock.
        connection = sqlite3.connect(self.database_path, timeout=3)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA busy_timeout = 3000')
        connection.execute('PRAGMA temp_store = MEMORY')
        connection.execute('PRAGMA cache_size = -8000')
        return connection

    def _initialize_database(self):
        with self._connection() as db:
            # Setting journal_mode writes to the database and can block startup.
            # Query first and only migrate older databases that are not yet WAL.
            if db.execute('PRAGMA journal_mode').fetchone()[0].lower() != 'wal':
                db.execute('PRAGMA journal_mode = WAL')
            db.execute('PRAGMA synchronous = NORMAL')
            db.execute('''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL, role TEXT NOT NULL, name TEXT NOT NULL,
                permissions TEXT NOT NULL DEFAULT '[]')''')
            db.execute('CREATE TABLE IF NOT EXISTS application_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')

    @staticmethod
    def _hash_password(password, salt=None):
        salt = salt or secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 200_000)
        return f'pbkdf2_sha256${salt}${digest.hex()}'

    @staticmethod
    def _verify_password(password, stored):
        if stored.startswith('pbkdf2_sha256$'):
            try:
                _, salt, expected = stored.split('$', 2)
                actual = Api._hash_password(password, salt)
                return hmac.compare_digest(actual, stored)
            except (TypeError, ValueError):
                return False
        # Migrate legacy plaintext credentials after their first successful login.
        return hmac.compare_digest(password, stored)

    @staticmethod
    def _public_user(row):
        return {
            'id': row['id'], 'name': row['name'], 'username': row['username'],
            'role': row['role'], 'permissions': json.loads(row['permissions'])
        }

    def _create_database_backup(self, directory):
        """Write a consistent copy, then swap it in without fighting Windows.

        The previous version always used one fixed ``pos_backup_latest.sqlite.tmp``
        name, so a second POS terminal, an antivirus scan or a cloud-sync client
        holding that file produced "WinError 32 - used by another process" and left
        the stray .tmp file behind."""
        temporary = None
        try:
            os.makedirs(directory, exist_ok=True)
            destination = os.path.join(directory, 'pos_backup_latest.sqlite')
            temporary = os.path.join(directory, f'pos_backup_{os.getpid()}_{int(time.time())}.tmp')
            with self._connection() as source, sqlite3.connect(temporary, timeout=10) as target:
                source.backup(target)
            last_error = None
            for attempt in range(6):
                try:
                    os.replace(temporary, destination)
                    last_error = None
                    break
                except OSError as exc:
                    last_error = exc
                    time.sleep(0.4 * (attempt + 1))
            if last_error is not None:
                # Keep a dated copy so no backup is ever lost to a locked file.
                fallback = os.path.join(directory, f'pos_backup_{time.strftime("%Y%m%d_%H%M%S")}.sqlite')
                os.replace(temporary, fallback)
                self._sweep_backup_temporaries(directory)
                return {'ok': True, 'path': fallback}
            self._sweep_backup_temporaries(directory)
            return {'ok': True, 'path': destination}
        except Exception as exc:
            if temporary and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except Exception:
                    pass
            _log_startup(f'backup failed: {exc}')
            return {'ok': False, 'error': f'Backup failed: {exc}'}

    @staticmethod
    def _sweep_backup_temporaries(directory):
        """Delete leftover .tmp files from interrupted or locked earlier backups."""
        try:
            for name in os.listdir(directory):
                if name.endswith('.tmp'):
                    path = os.path.join(directory, name)
                    if time.time() - os.path.getmtime(path) > 120:
                        try:
                            os.unlink(path)
                        except OSError:
                            pass
        except Exception:
            pass

    def _backup_after_write(self):
        """Schedule a backup without delaying the POS write/UI bridge response.

        Nothing is copied during the first minute after launch and no more often
        than every five minutes: a backup folder on a USB disk or network share is
        slow, and doing that work while the counter staff are clicking is what made
        the window stop responding."""
        if time.monotonic() - _PROCESS_STARTED < 60:
            return {'ok': True, 'skipped': True}
        with self._connection() as db:
            row = db.execute("SELECT value FROM settings WHERE key = 'backup_directory'").fetchone()
        if not row or not row['value']:
            return {'ok': True, 'skipped': True}
        with self._database_lock:
            now = time.monotonic()
            if self._backup_in_progress or now - self._last_automatic_backup < 300:
                return {'ok': True, 'skipped': True}
            self._last_automatic_backup = now
            self._backup_in_progress = True

        def backup_in_background():
            try:
                self._create_database_backup(row['value'])
            finally:
                with self._database_lock:
                    self._backup_in_progress = False

        threading.Thread(target=backup_in_background, name='pos-backup', daemon=True).start()
        return {'ok': True, 'scheduled': True}

    def get_boot_data(self):
        """A fresh process deliberately has no session; only disk-backed users decide login."""
        return {'users': self.list_users(), 'state': self.load_state()}

    def list_users(self):
        with self._connection() as db:
            rows = db.execute('SELECT id, name, username, password, role, permissions FROM users ORDER BY id').fetchall()
        return [self._public_user(row) for row in rows]

    def authenticate(self, username, password):
        username = (username or '').strip()
        password = password or ''
        with self._connection() as db:
            row = db.execute('SELECT id, name, username, password, role, permissions FROM users WHERE username = ?', (username,)).fetchone()
            if not row or not self._verify_password(password, row['password']):
                return {'ok': False, 'error': 'Invalid credentials.'}
            if not row['password'].startswith('pbkdf2_sha256$'):
                db.execute('UPDATE users SET password = ? WHERE id = ?', (self._hash_password(password), row['id']))
                row = db.execute('SELECT id, name, username, password, role, permissions FROM users WHERE id = ?', (row['id'],)).fetchone()
        return {'ok': True, 'user': self._public_user(row)}

    def save_user(self, user, user_id=None):
        username = (user.get('username') or '').strip()
        if not username or not user.get('name') or (user_id is None and not user.get('password')):
            return {'ok': False, 'error': 'Name and username are required; a password is required for a new user.'}
        if user.get('password') and len(user['password']) < 8:
            return {'ok': False, 'error': 'Passwords must contain at least 8 characters.'}
        try:
            with self._connection() as db:
                if user_id is None:
                    cursor = db.execute('INSERT INTO users (username, password, role, name, permissions) VALUES (?, ?, ?, ?, ?)',
                        (username, self._hash_password(user['password']), user.get('role', 'Cashier'), user['name'], json.dumps(user.get('permissions', []))))
                    user_id = cursor.lastrowid
                else:
                    existing = db.execute('SELECT role FROM users WHERE id = ?', (user_id,)).fetchone()
                    if not existing:
                        return {'ok': False, 'error': 'The requested user account was not found.'}
                    # Do not allow the only administrator to be demoted. Without this
                    # guard, a valid account set could become impossible to administer.
                    if existing['role'] == 'Admin' and user.get('role', 'Cashier') != 'Admin':
                        admin_count = db.execute("SELECT COUNT(*) FROM users WHERE role = 'Admin'").fetchone()[0]
                        if admin_count <= 1:
                            return {'ok': False, 'error': 'The last administrator account cannot be changed to a non-admin role.'}
                    if user.get('password'):
                        db.execute('UPDATE users SET username=?, password=?, role=?, name=?, permissions=? WHERE id=?',
                            (username, self._hash_password(user['password']), user.get('role', 'Cashier'), user['name'], json.dumps(user.get('permissions', [])), user_id))
                    else:
                        db.execute('UPDATE users SET username=?, role=?, name=?, permissions=? WHERE id=?',
                            (username, user.get('role', 'Cashier'), user['name'], json.dumps(user.get('permissions', [])), user_id))
            self._backup_after_write()
            return {'ok': True, 'users': self.list_users(), 'id': user_id}
        except sqlite3.IntegrityError:
            return {'ok': False, 'error': 'That username already exists.'}

    def delete_user(self, user_id):
        with self._connection() as db:
            count = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            if count <= 1:
                return {'ok': False, 'error': 'The last user account cannot be deleted.'}
            user = db.execute('SELECT role FROM users WHERE id = ?', (user_id,)).fetchone()
            if not user:
                return {'ok': False, 'error': 'The requested user account was not found.'}
            if user['role'] == 'Admin':
                admin_count = db.execute("SELECT COUNT(*) FROM users WHERE role = 'Admin'").fetchone()[0]
                if admin_count <= 1:
                    return {'ok': False, 'error': 'The last administrator account cannot be deleted.'}
            if db.execute('DELETE FROM users WHERE id = ?', (user_id,)).rowcount != 1:
                return {'ok': False, 'error': 'The requested user account was not found.'}
        self._backup_after_write()
        return {'ok': True, 'users': self.list_users()}

    def load_state(self):
        with self._connection() as db:
            row = db.execute("SELECT value FROM application_state WHERE key = 'pos_state'").fetchone()
        return json.loads(row['value']) if row else {}

    def save_state(self, state):
        # Users are intentionally excluded: they always use direct SQL writes above.
        try:
            if not isinstance(state, dict):
                return {'ok': False, 'error': 'POS data payload is invalid; expected an object.'}
            state = {key: value for key, value in state.items() if key != 'users'}
            encoded = json.dumps(state, ensure_ascii=False, separators=(',', ':'))
            with self._database_lock:
                with self._connection() as db:
                    db.execute("INSERT INTO application_state(key, value) VALUES ('pos_state', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                               (encoded,))
                backup = self._backup_after_write()
            return {'ok': True, 'backupError': backup.get('error', '')}
        except (TypeError, ValueError) as exc:
            return {'ok': False, 'error': f'POS data cannot be encoded: {exc}'}
        except sqlite3.Error as exc:
            return {'ok': False, 'error': f'POS database write failed: {exc}'}
        except Exception as exc:
            return {'ok': False, 'error': f'POS data save failed: {exc}'}

    def get_printer_config(self):
        with self._connection() as db:
            row = db.execute("SELECT value FROM settings WHERE key = 'printer_config'").fetchone()
        try:
            return json.loads(row['value']) if row else {}
        except (TypeError, ValueError):
            return {}

    def save_printer_config(self, config):
        try:
            with self._connection() as db:
                db.execute("INSERT INTO settings(key, value) VALUES ('printer_config', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(config),))
            return {'ok': True}
        except (TypeError, ValueError, sqlite3.Error) as exc:
            return {'ok': False, 'error': f'Printer settings save failed: {exc}'}

    def get_system_printers(self):
        """Return installed system print queues; physical-device discovery is driver/OS-owned."""
        res_container = []
        exc_container = []

        def enumerate_printers():
            try:
                if sys.platform == 'win32':
                    import win32print
                    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
                    res_container.append({'printers': [p[2] for p in win32print.EnumPrinters(flags)], 'error': ''})
                    return
                result = subprocess.run(['lpstat', '-e'], capture_output=True, text=True, check=False)
                if result.returncode:
                    res_container.append({'printers': [], 'error': result.stderr.strip() or 'The system print service did not return any printers.'})
                else:
                    res_container.append({'printers': [line.strip() for line in result.stdout.splitlines() if line.strip()], 'error': ''})
            except Exception as exc:
                exc_container.append(exc)

        t = threading.Thread(target=enumerate_printers, daemon=True)
        t.start()
        t.join(timeout=3.0)
        if t.is_alive():
            return {'printers': [], 'error': 'Printer discovery timed out after 3 seconds.'}
        if exc_container:
            return {'printers': [], 'error': f'Unable to read system printers: {exc_container[0]}'}
        return res_container[0] if res_container else {'printers': [], 'error': 'No response from printer service.'}

    def test_printer(self, printer_name, receipt_type='Test', cut_mode='escpos_full', config=None):
        """Print a full sample document using the saved branding and paper width.

        The test used to ignore the Receipt Branding settings and printed an
        empty item list, so a changed restaurant name, tagline, address, phone,
        footer or paper width never appeared on the test print."""
        config = config or {}
        is_kot = receipt_type.upper() == 'KOT'
        receipt = {
            'title': f'TEST {receipt_type.upper()}',
            'orderId': 'TEST-001',
            'isKot': is_kot,
            'cutMode': cut_mode,
            'date': time.strftime('%d-%m-%Y'),
            'time': time.strftime('%I:%M %p'),
            'tableName': 'T1' if is_kot else '',
            'serverName': 'TEST STAFF',
            'items': [
                {'name': 'SAMPLE CHICKEN KARAHI (FULL)', 'qty': 1, 'price': 1450, 'notes': 'LESS SPICY'},
                {'name': 'SAMPLE GARLIC NAAN', 'qty': 2, 'price': 60},
            ],
            'subtotal': 1570.0,
            'grandTotal': 1570.0,
            'orderNote': 'SAMPLE ORDER INSTRUCTION - SERVE HOT',
            'restaurantName': config.get('restaurantName'),
            'header': config.get('receiptHeader'),
            'restaurantTagline': config.get('restaurantTagline'),
            'restaurantAddress': config.get('restaurantAddress'),
            'restaurantPhone': config.get('restaurantPhone'),
            'receiptFooter': config.get('receiptFooter'),
            'paperWidth': config.get('paperWidth') or '80mm',
        }
        return self.print_direct(printer_name, receipt)

    @classmethod
    def _print_with_windows_driver(cls, printer_name, blocks, width):
        """Print through the Star Windows driver so its Document Bottom cut applies.

        Bold and double-size lines use matching fonts, so the driver output looks
        like the approved receipt design rather than uniform plain text."""
        import win32ui

        printer_dc = win32ui.CreateDC()
        printer_dc.CreatePrinterDC(printer_name)
        fonts = {
            (False, 1): win32ui.CreateFont({'name': 'Consolas', 'height': -24, 'weight': 400}),
            (True, 1): win32ui.CreateFont({'name': 'Consolas', 'height': -24, 'weight': 700}),
            (False, 2): win32ui.CreateFont({'name': 'Consolas', 'height': -44, 'weight': 400}),
            (True, 2): win32ui.CreateFont({'name': 'Consolas', 'height': -44, 'weight': 700}),
        }
        printer_dc.StartDoc('POS Receipt')
        try:
            printer_dc.StartPage()
            printer_dc.SelectObject(fonts[(False, 1)])
            paper = printer_dc.GetTextExtent('0' * width)[0]
            x, y = 24, 24
            for block in blocks:
                text = cls._flatten(block, width)
                printer_dc.SelectObject(fonts[(bool(block.get('bold')), 2 if (block.get('size') or 1) > 1 else 1)])
                extent = printer_dc.GetTextExtent(text or 'Ag')
                left = x + max(0, (paper - extent[0]) // 2) if block['align'] == 'c' else x
                printer_dc.TextOut(left, y, text)
                y += extent[1] + 4
            printer_dc.EndPage()
            printer_dc.EndDoc()
        except Exception:
            printer_dc.AbortDoc()
            raise
        finally:
            printer_dc.DeleteDC()

    # --- Receipt composition -------------------------------------------------
    # Every printed document is described as a list of styled blocks so the exact
    # layout of "Receipts design.html" (centred bold headings, large table/token
    # and total lines, = and - rules, QTY/AMOUNT columns) survives on both print
    # paths: the Windows driver and raw ESC/POS thermal output.

    @staticmethod
    def _columns(paper_width):
        return 32 if paper_width == '58mm' else 48

    @classmethod
    def _compose_receipt(cls, receipt_data):
        width = cls._columns(receipt_data.get('paperWidth', '80mm'))

        def block(text='', align='l', bold=False, size=1):
            return {'t': str(text), 'align': align, 'bold': bold, 'size': size}

        def rule(char='-'):
            return block(char * width, 'l')

        def _wrap_text(value, limit):
            """Split on word boundaries so nothing is cut off the paper."""
            limit = max(4, limit)
            words, lines, current = str(value).split(), [], ''
            for word in words:
                while len(word) > limit:
                    if current:
                        lines.append(current)
                        current = ''
                    lines.append(word[:limit])
                    word = word[limit:]
                candidate = f'{current} {word}'.strip()
                if len(candidate) > limit:
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            if current:
                lines.append(current)
            return lines or ['']

        def wrapped(value, prefix='', size=1):
            # A double-size line prints twice as wide, so it has half the columns.
            value = str(value or '').strip()
            if not value:
                return []
            columns = max(8, width // (size or 1))
            lines = _wrap_text(value, columns - len(prefix))
            indent = ' ' * len(prefix)
            return [(prefix if index == 0 else indent) + line for index, line in enumerate(lines)]

        def centered(value, bold=False, size=1):
            return [block(part, 'c', bold, size) for part in wrapped(value, size=size)]

        def two(left, right, bold=False, size=1):
            """A left/right column line; a long left label continues on more lines."""
            right = str(right)
            columns = max(8, width // (size or 1))
            lines = _wrap_text(str(left), columns - len(right) - 1)
            blocks_out = [block(line, 'l', bold, size) for line in lines[:-1]]
            blocks_out.append({'t': None, 'left': lines[-1], 'right': right,
                               'align': 'l', 'bold': bold, 'size': size})
            return blocks_out

        blocks = []
        items = receipt_data.get('items', []) or []

        # The Receipt Branding Customization values apply to every document,
        # the kitchen ticket included, so a renamed restaurant always prints.
        brand_name = str(receipt_data.get('restaurantName') or receipt_data.get('header') or '').strip()

        if receipt_data.get('isKot'):
            if brand_name:
                blocks += centered(brand_name.upper(), bold=True)
            if receipt_data.get('restaurantTagline'):
                blocks += centered(receipt_data['restaurantTagline'])
            blocks += centered('*** KITCHEN TICKET ***', bold=True)
            blocks.append(rule('='))
            if receipt_data.get('tableName'):
                blocks += centered(f"TABLE: {receipt_data['tableName']}", bold=True, size=2)
                blocks.append(rule('-'))
            blocks.append(block(f"KOT NO : {receipt_data.get('orderId', '')}"))
            if receipt_data.get('date') or receipt_data.get('time'):
                stamp = ' '.join(part for part in [str(receipt_data.get('date') or ''), str(receipt_data.get('time') or '')] if part)
                blocks.append(block(f"TIME   : {stamp}"))
            if receipt_data.get('serverName'):
                blocks.append(block(f"SERVER : {receipt_data['serverName']}"))
            if receipt_data.get('orderType'):
                blocks.append(block(f"TYPE   : {receipt_data['orderType']}"))
            blocks += [rule('=')] + two('ITEM DESCRIPTION', 'QTY', bold=True) + [rule('=')]
            for item in items:
                blocks += two(str(item.get('name', '')).upper(), f"{item.get('qty', 0)}x", bold=True)
                if item.get('notes'):
                    blocks += [block(part) for part in wrapped(str(item['notes']).upper(), '  * NOTE: ')]
            if str(receipt_data.get('orderNote') or '').strip():
                blocks.append(rule('-'))
                blocks += centered('*** ORDER INSTRUCTIONS ***', bold=True)
                blocks += [block(part, 'l', True) for part in wrapped(str(receipt_data['orderNote']).upper())]
            blocks.append(rule('='))
            blocks += centered('[ END OF ORDER - COOK PROMPTLY ]', bold=True)
            return blocks, width

        order_type = receipt_data.get('orderType', '')
        is_preview = receipt_data.get('isPreview', False)
        is_delivery = order_type == 'Delivery'
        is_takeaway = order_type == 'Takeaway'
        payment_method = receipt_data.get('paymentMethod', '')

        blocks += centered((brand_name or 'MUGHAL-E-AZAM RESTAURANT').upper(), bold=True, size=2)
        blocks += centered(receipt_data.get('restaurantTagline'))
        blocks += centered(receipt_data.get('restaurantAddress'))
        if receipt_data.get('restaurantPhone'):
            blocks += centered(f"TEL: {receipt_data['restaurantPhone']}")
        title = '*** PREVIEW CHECK (UNPAID) ***' if is_preview else (
            '*** TAKEAWAY ORDER ***' if is_takeaway else (
                '*** DELIVERY RECEIPT ***' if is_delivery else (
                    receipt_data.get('title') or '*** FINAL CASH RECEIPT ***')))
        blocks.append(rule('='))
        blocks += centered(title, bold=True)
        blocks.append(rule('='))
        if is_takeaway:
            blocks += centered(f"TOKEN: #{receipt_data.get('orderId', '')}", bold=True, size=2)
            blocks.append(rule('-'))
        blocks.append(block(f"{'ORD NO' if is_delivery or is_takeaway else 'INV NO'} : {receipt_data.get('orderId', '')}"))
        if receipt_data.get('date') or receipt_data.get('time'):
            stamp = ' '.join(part for part in [str(receipt_data.get('date') or ''), str(receipt_data.get('time') or '')] if part)
            blocks.append(block(f"DATE   : {stamp}"))
        if receipt_data.get('tableName'):
            server = receipt_data.get('serverName')
            blocks.append(block(f"TABLE  : {receipt_data['tableName']}" + (f" | SERVER: {server}" if server else '')))
        elif receipt_data.get('serverName'):
            blocks.append(block(f"SERVER : {receipt_data['serverName']}"))
        if is_takeaway:
            if receipt_data.get('customerName'):
                blocks.append(block(f"CUST   : {receipt_data['customerName']}"))
            if receipt_data.get('customerPhone'):
                blocks.append(block(f"PHONE  : {receipt_data['customerPhone']}"))
            blocks.append(block(f"STATUS : {'PAID (' + str(payment_method) + ')' if payment_method else 'UNPAID'}"))
        if is_delivery:
            blocks.append(block(f"PAYMENT: {payment_method or 'CASH ON DELIVERY'}"))
            blocks += [rule('-'), block('CUSTOMER DETAILS:', bold=True)]
            if receipt_data.get('customerName'):
                blocks.append(block(f"NAME : {receipt_data['customerName']}"))
            if receipt_data.get('customerPhone'):
                blocks.append(block(f"TEL  : {receipt_data['customerPhone']}"))
            if receipt_data.get('customerAddress'):
                blocks.append(block('ADDR :'))
                blocks += [block(part) for part in wrapped(receipt_data['customerAddress'])]
        blocks += [rule('-')] + two('QTY DESCRIPTION', 'PRICE (RS.)', bold=True) + [rule('-')]
        for item in items:
            qty, name, price = item.get('qty', 0), item.get('name', ''), item.get('price', 0)
            blocks += two(f"{qty} x {name}", f"{float(qty or 0) * float(price or 0):.2f}")
        blocks.append(rule('-'))
        blocks += two('SUB TOTAL', f"{float(receipt_data.get('subtotal') or 0):.2f}")
        if float(receipt_data.get('discount') or 0):
            blocks += two('DISCOUNT', f"-{float(receipt_data.get('discount') or 0):.2f}")
        if float(receipt_data.get('deliveryFee') or 0):
            blocks += two('DELIVERY FEE', f"{float(receipt_data.get('deliveryFee') or 0):.2f}")
        total_label = 'EST. TOTAL' if is_preview else (
            'COLLECT CASH' if is_delivery and 'cash' in str(payment_method).lower() else 'TOTAL PAID')
        blocks.append(rule('='))
        blocks += two(total_label, f"Rs.{float(receipt_data.get('grandTotal') or 0):.2f}", bold=True, size=2)
        blocks.append(rule('='))
        if float(receipt_data.get('cashTendered') or 0):
            blocks += two('CASH', f"{float(receipt_data.get('cashTendered') or 0):.2f}")
            blocks += two('CHANGE', f"{float(receipt_data.get('changeDue') or 0):.2f}")
        if str(receipt_data.get('orderNote') or '').strip():
            blocks.append(rule('-'))
            blocks += centered('ORDER INSTRUCTIONS', bold=True)
            blocks += [block(part) for part in wrapped(str(receipt_data['orderNote']).upper())]
        custom_footer = str(receipt_data.get('receiptFooter') or '').strip()
        if is_preview:
            closing = '* NO PAYMENT RECEIVED *\nPLEASE PRESENT TO CASHIER'
        elif is_takeaway:
            closing = '[ READY FOR COUNTER PICKUP ]\nTHANK YOU FOR ORDERING!'
        elif is_delivery and 'cash' in str(payment_method).lower():
            closing = '* CASH ON DELIVERY (COD) *\nDRIVER: PLEASE COLLECT EXACT AMOUNT'
        else:
            closing = custom_footer or 'THANK YOU FOR YOUR VISIT!\nPLEASE COME AGAIN'
        blocks.append(block(''))
        for part in str(closing).split('\n'):
            blocks += centered(part, bold=True)
        # The custom footer is part of the branding settings, so it prints on
        # takeaway, delivery and preview documents too, under their own closing.
        if custom_footer and custom_footer not in str(closing):
            for part in custom_footer.split('\n'):
                blocks += centered(part)
        return blocks, width

    @staticmethod
    def _flatten(block, width):
        """Render one styled block as plain text, honouring the column layout.

        Text is never cut here: composition already wraps every line to the
        paper's column count (halved for double-size lines), so trimming again
        would drop the end of long names, headings and totals."""
        columns = max(8, width // (block.get('size') or 1))
        if block.get('t') is None:
            left, right = str(block['left']), str(block['right'])
            spaces = max(1, columns - len(left) - len(right))
            return left + (' ' * spaces) + right
        return str(block['t'])

    @classmethod
    def _render_plain(cls, blocks, width):
        rendered = []
        for block in blocks:
            text = cls._flatten(block, width)
            if block['align'] == 'c':
                columns = max(8, width // (block.get('size') or 1))
                text = text.center(columns)
            rendered.append(text)
        return '\n'.join(rendered) + '\n'

    @classmethod
    def _render_escpos(cls, blocks, width):
        """Same layout with real thermal emphasis (centring, bold, double size)."""
        out = bytearray(b'\x1b@')  # initialise
        align_codes = {'l': b'\x1ba\x00', 'c': b'\x1ba\x01', 'r': b'\x1ba\x02'}
        for block in blocks:
            out += align_codes.get(block['align'], align_codes['l'])
            out += b'\x1bE\x01' if block.get('bold') else b'\x1bE\x00'
            out += b'\x1d!\x11' if (block.get('size') or 1) > 1 else b'\x1d!\x00'
            out += cls._flatten(block, width).encode('utf-8', 'replace') + b'\n'
        out += b'\x1bE\x00\x1d!\x00\x1ba\x00'
        return bytes(out)

    def print_direct(self, printer_name, receipt_data):
        if not printer_name:
            return {'status': 'error', 'message': 'Select a system printer first.'}

        res_container = []
        exc_container = []

        def execute_print():
            try:
                blocks, width = self._compose_receipt(receipt_data)
                cut_mode = receipt_data.get('cutMode', 'escpos_full')
                cut_commands = {
                    'star': b'\x1b\x69',             # Legacy Star (ESC i) setting.
                    'star_full': None,                # Windows Star driver bottom cut.
                    'star_raw_full': b'\x1b\x69',    # Star line-mode raw full cut.
                    'star_partial': b'\x1b\x6d',     # Star line-mode partial cut.
                    'escpos': b'\x1dV\x42\x00',     # Legacy ESC/POS setting.
                    'escpos_full': b'\x1dV\x00',
                    'escpos_partial': b'\x1dV\x01',
                    'none': b'',
                }
                if cut_mode not in cut_commands:
                    res_container.append({'status': 'error', 'message': 'The selected printer cut profile is invalid.'})
                    return
                if cut_mode == 'star_full' and sys.platform == 'win32':
                    try:
                        self._print_with_windows_driver(printer_name, blocks, width)
                        res_container.append({'status': 'success', 'message': f'Print job sent to {printer_name} using the Windows Star driver.'})
                        return
                    except Exception as exc:
                        res_container.append({'status': 'error', 'message': f'Windows driver print failed: {exc}'})
                        return
                payload = self._render_escpos(blocks, width) + (b'\n' * 5) + cut_commands[cut_mode]
                if sys.platform == 'win32':
                    import win32print
                    printer = win32print.OpenPrinter(printer_name)
                    try:
                        win32print.StartDocPrinter(printer, 1, ('POS Receipt', None, 'RAW'))
                        win32print.StartPagePrinter(printer)
                        win32print.WritePrinter(printer, payload)
                        win32print.EndPagePrinter(printer)
                        win32print.EndDocPrinter(printer)
                    finally:
                        win32print.ClosePrinter(printer)
                else:
                    result = subprocess.run(['lp', '-d', printer_name, '-o', 'raw'], input=payload, capture_output=True, check=False)
                    if result.returncode:
                        raise RuntimeError(result.stderr.decode(errors='replace').strip())
                res_container.append({'status': 'success', 'message': f'Print job sent to {printer_name}.'})
            except Exception as exc:
                exc_container.append(exc)

        t = threading.Thread(target=execute_print, daemon=True)
        t.start()
        t.join(timeout=5.0)
        if t.is_alive():
            return {'status': 'error', 'message': f'Printing to {printer_name} timed out after 5 seconds.'}
        if exc_container:
            return {'status': 'error', 'message': f'Print failed: {exc_container[0]}'}
        return res_container[0] if res_container else {'status': 'error', 'message': 'No response from print driver.'}

    def select_backup_folder(self):
        selected = self.window.create_file_dialog(webview.FOLDER_DIALOG) if self.window else None
        if not selected:
            return {'ok': False, 'cancelled': True}
        directory = selected[0] if isinstance(selected, (list, tuple)) else selected
        with self._connection() as db:
            db.execute("INSERT INTO settings(key, value) VALUES ('backup_directory', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (directory,))
        backup = self._create_database_backup(directory)
        if not backup['ok']:
            return backup
        return {'ok': True, 'directory': directory, 'path': backup['path']}

    def create_backup_now(self):
        directory = self.get_backup_directory()
        if not directory:
            return {'ok': False, 'error': 'Select a custom backup folder first.'}
        return self._create_database_backup(directory)

    def get_backup_directory(self):
        with self._connection() as db:
            row = db.execute("SELECT value FROM settings WHERE key = 'backup_directory'").fetchone()
        return row['value'] if row else ''

    def restore_from_directory(self):
        selected = self.window.create_file_dialog(webview.FOLDER_DIALOG) if self.window else None
        if not selected:
            return {'ok': False, 'cancelled': True}
        directory = selected[0] if isinstance(selected, (list, tuple)) else selected
        source = os.path.join(directory, 'pos_backup_latest.sqlite')
        if not os.path.isfile(source):
            return {'ok': False, 'error': 'pos_backup_latest.sqlite was not found in the selected folder.'}
        fd, temporary = tempfile.mkstemp(dir=os.path.dirname(self.database_path), suffix='.sqlite')
        os.close(fd)
        try:
            shutil.copy2(source, temporary)
            with sqlite3.connect(temporary) as candidate:
                if candidate.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    return {'ok': False, 'error': 'The selected backup database failed its integrity check.'}
                candidate.execute('SELECT 1 FROM users LIMIT 1')
            # Connections are short-lived, so no connection pool remains open here.
            os.replace(temporary, self.database_path)
            return {'ok': True, 'boot': self.get_boot_data()}
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


class SharedApiServer(http.server.ThreadingHTTPServer):
    """Small authenticated LAN gateway for a counter-owned POS database."""
    daemon_threads = True

    def __init__(self, address, api, token):
        self.api = api
        self.token = token
        super().__init__(address, SharedApiHandler)


class SharedApiHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _reply(self, status, payload):
        encoded = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _allowed(self):
        return hmac.compare_digest(self.headers.get('X-POS-Token', ''), self.server.token)

    def _body(self):
        length = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(length).decode('utf-8')) if length else {}

    def do_GET(self):
        if not self._allowed():
            return self._reply(401, {'ok': False, 'error': 'Invalid shared POS token.'})
        if self.path == '/v1/boot':
            return self._reply(200, self.server.api.get_boot_data())
        if self.path == '/v1/backup-directory':
            return self._reply(200, {'directory': self.server.api.get_backup_directory()})
        return self._reply(404, {'ok': False, 'error': 'Unknown shared POS endpoint.'})

    def do_POST(self):
        if not self._allowed():
            return self._reply(401, {'ok': False, 'error': 'Invalid shared POS token.'})
        try:
            data = self._body()
            if self.path == '/v1/state':
                result = self.server.api.save_state(data.get('state', {}))
            elif self.path == '/v1/authenticate':
                result = self.server.api.authenticate(data.get('username'), data.get('password'))
            elif self.path == '/v1/users':
                result = self.server.api.save_user(data.get('user', {}), data.get('userId'))
            elif self.path == '/v1/backup':
                result = self.server.api.create_backup_now()
            else:
                return self._reply(404, {'ok': False, 'error': 'Unknown shared POS endpoint.'})
            self._reply(200, result)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._reply(400, {'ok': False, 'error': f'Invalid request: {exc}'})
        except Exception as exc:
            self._reply(500, {'ok': False, 'error': f'Shared POS server error: {exc}'})

    def do_DELETE(self):
        if not self._allowed():
            return self._reply(401, {'ok': False, 'error': 'Invalid shared POS token.'})
        if not self.path.startswith('/v1/users/'):
            return self._reply(404, {'ok': False, 'error': 'Unknown shared POS endpoint.'})
        try:
            self._reply(200, self.server.api.delete_user(int(self.path.rsplit('/', 1)[1])))
        except (ValueError, IndexError):
            self._reply(400, {'ok': False, 'error': 'Invalid user id.'})


class RemoteApi:
    """pywebview bridge used by a second terminal; printing always stays local."""
    def __init__(self, server_url, token, local_settings_path):
        self.server_url = server_url.rstrip('/')
        self.token = token
        self.window = None
        self.local_api = Api(local_settings_path)

    def _request(self, path, method='GET', payload=None):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        request = urllib.request.Request(
            f'{self.server_url}{path}', data=data, method=method,
            headers={'X-POS-Token': self.token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            try:
                return json.loads(exc.read().decode('utf-8'))
            except Exception:
                return {'ok': False, 'error': f'Shared POS server returned HTTP {exc.code}.'}
        except (urllib.error.URLError, TimeoutError) as exc:
            return {'ok': False, 'error': f'Cannot reach shared POS server: {exc}'}

    def get_boot_data(self): return self._request('/v1/boot')
    def get_printer_config(self): return self.local_api.get_printer_config()
    def save_printer_config(self, config): return self.local_api.save_printer_config(config)
    def authenticate(self, username, password): return self._request('/v1/authenticate', 'POST', {'username': username, 'password': password})
    def save_state(self, state): return self._request('/v1/state', 'POST', {'state': state})
    def save_user(self, user, user_id=None): return self._request('/v1/users', 'POST', {'user': user, 'userId': user_id})
    def delete_user(self, user_id): return self._request(f'/v1/users/{user_id}', 'DELETE')
    def get_backup_directory(self): return self._request('/v1/backup-directory').get('directory', '')
    def create_backup_now(self): return self._request('/v1/backup', 'POST')

    # Backups are centrally owned; OS printers remain per terminal.
    def select_backup_folder(self): return {'ok': False, 'error': 'Select backup folders on the main counter PC.'}
    def restore_from_directory(self): return {'ok': False, 'error': 'Restore backups on the main counter PC.'}
    def get_system_printers(self): return Api.get_system_printers(self)
    def test_printer(self, printer_name, receipt_type='Test', cut_mode='escpos_full', config=None): return Api.test_printer(self, printer_name, receipt_type, cut_mode, config)
    def print_direct(self, printer_name, receipt_data): return Api.print_direct(self, printer_name, receipt_data)


def main():
    parser = argparse.ArgumentParser(description='Mughal-E-Azam POS')
    parser.add_argument('--share-lan', action='store_true', help='Share this counter database with another POS terminal.')
    parser.add_argument('--server-host', default='0.0.0.0', help='LAN address to bind when --share-lan is enabled.')
    parser.add_argument('--server-port', type=int, default=8765, help='LAN port for shared POS access.')
    parser.add_argument('--server-token', default=os.environ.get('MUGHAL_POS_TOKEN', ''), help='Shared POS token; required for LAN mode.')
    parser.add_argument('--server-url', default=os.environ.get('MUGHAL_POS_SERVER', ''), help='Use the specified main-counter shared POS server.')
    args = parser.parse_args()
    if args.server_url and not args.server_token:
        parser.error('--server-token (or MUGHAL_POS_TOKEN) is required with --server-url.')
    if args.share_lan and not args.server_token:
        parser.error('--server-token (or MUGHAL_POS_TOKEN) is required with --share-lan.')

    asset_server = None
    try:
        api = RemoteApi(args.server_url, args.server_token, os.path.join(get_data_dir(), 'terminal-settings.sqlite')) if args.server_url else Api(os.path.join(get_data_dir(), 'database.sqlite'))
        # Start the UI endpoint before the window exists.  This replaces the
        # file-origin launch path and its fragile browser-side startup polling.
        asset_server = LocalAssetServer(get_base_dir(), api)
        asset_server.start()
        if args.share_lan:
            threading.Thread(target=SharedApiServer((args.server_host, args.server_port), api, args.server_token).serve_forever, daemon=True).start()
        _prepare_webview_runtime()
        _log_startup(f'starting interface at {asset_server.url}')
        # The window starts hidden and is only shown once the interface has
        # finished loading. Clicking a visible-but-still-starting WebView2 window
        # queued mouse input against a browser process that was not yet accepting
        # it, which is what made the POS freeze unless staff waited ~10 seconds.
        api.window = webview.create_window(
            'MUGHAL-E-AZAM - Restaurant', asset_server.url, js_api=api,
            width=1280, height=800, resizable=True, min_size=(900, 600), hidden=True)

        window_shown = threading.Event()

        def reveal_window(reason):
            if window_shown.is_set():
                return
            window_shown.set()
            try:
                api.window.show()
                _log_startup(f'window shown ({reason})')
            except Exception as exc:
                _log_startup(f'window show failed ({reason}): {exc}')

        def reveal_when_ready():
            # Safety net: never leave an invisible window if the runtime does not
            # report the load event.
            time.sleep(20)
            reveal_window('timeout fallback')

        try:
            api.window.events.loaded += lambda: (
                _log_startup('interface loaded in WebView2'), reveal_window('interface loaded'))
        except Exception:
            reveal_window('load event unavailable')
        threading.Thread(target=reveal_when_ready, name='pos-window-reveal', daemon=True).start()
        if sys.platform == 'win32':
            try:
                # Never fall back to the legacy IE (MSHTML) engine: Vue 3 and fetch()
                # do not run there, which looks exactly like a frozen window.
                webview.start(gui='edgechromium', private_mode=False)
            except Exception as exc:
                raise RuntimeError(
                    'The Microsoft Edge WebView2 Runtime is missing or damaged on this PC. '
                    'Install "Microsoft Edge WebView2 Runtime (Evergreen)" from Microsoft and start the POS again.'
                    f'\n\nDetails: {exc}')
        else:
            webview.start(private_mode=False)
        _log_startup('POS window closed')
    except Exception as exc:
        # Do not leave an invisible process holding a launch mutex. The next
        # launch is always allowed, and this failure is visible in a console log.
        print(f'POS startup failed: {exc}', file=sys.stderr)
        _log_startup(f'startup failed: {exc}')
        raise
    finally:
        if asset_server:
            asset_server.close()


if __name__ == '__main__':
    main()
