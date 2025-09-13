import ctypes
import ctypes.util
import ctypes.wintypes as wintypes  # type: ignore[attr-defined]
import math
import random
import time
import argparse
import sys


# ---- X11 / XScreenSaver bindings via ctypes (no external deps) ----


def _load_library(names: list[str]) -> ctypes.CDLL:
	for name in names:
		path = ctypes.util.find_library(name) or name
		try:
			return ctypes.CDLL(path)
		except OSError:
			continue
	raise OSError(f"Unable to load libraries: {names}")


libX11 = _load_library(["X11", "libX11.so.6"])
libXss = _load_library(["Xss", "libXss.so.1"])


# Basic X11 types
Display_p = ctypes.c_void_p
Window = ctypes.c_ulong
Cursor = ctypes.c_ulong
Bool = ctypes.c_int
Status = ctypes.c_int
Time_t = ctypes.c_ulong


# Cursor font constant for left arrow (from cursorfont.h)
XC_left_ptr = 68

# Event masks and constants
KeyPress = 2
KeyPressMask = 1 << 0
GrabModeAsync = 1
AnyModifier = 1 << 15


class XScreenSaverInfo(ctypes.Structure):
	_fields_ = [
		("window", Window),
		("state", ctypes.c_int),
		("kind", ctypes.c_int),
		("til_or_since", ctypes.c_ulong),
		("idle", ctypes.c_ulong),
		("eventMask", ctypes.c_ulong),
	]


class XKeyEvent(ctypes.Structure):
	_fields_ = [
		("type", ctypes.c_int),
		("serial", ctypes.c_ulong),
		("send_event", Bool),
		("display", Display_p),
		("window", Window),
		("root", Window),
		("subwindow", Window),
		("time", ctypes.c_ulong),
		("x", ctypes.c_int),
		("y", ctypes.c_int),
		("x_root", ctypes.c_int),
		("y_root", ctypes.c_int),
		("state", ctypes.c_uint),
		("keycode", ctypes.c_uint),
		("same_screen", Bool),
	]


class XEvent(ctypes.Union):
	_fields_ = [("type", ctypes.c_int), ("xkey", XKeyEvent), ("pad", ctypes.c_long * 24)]


# Function signatures
libX11.XOpenDisplay.restype = Display_p
libX11.XOpenDisplay.argtypes = [ctypes.c_char_p]

libX11.XCloseDisplay.restype = ctypes.c_int
libX11.XCloseDisplay.argtypes = [Display_p]

libX11.XDefaultScreen.restype = ctypes.c_int
libX11.XDefaultScreen.argtypes = [Display_p]

libX11.XRootWindow.restype = Window
libX11.XRootWindow.argtypes = [Display_p, ctypes.c_int]

libX11.XDisplayWidth.restype = ctypes.c_int
libX11.XDisplayWidth.argtypes = [Display_p, ctypes.c_int]

libX11.XDisplayHeight.restype = ctypes.c_int
libX11.XDisplayHeight.argtypes = [Display_p, ctypes.c_int]

libX11.XQueryPointer.restype = Bool
libX11.XQueryPointer.argtypes = [
	Display_p,
	Window,
	ctypes.POINTER(Window),
	ctypes.POINTER(Window),
	ctypes.POINTER(ctypes.c_int),
	ctypes.POINTER(ctypes.c_int),
	ctypes.POINTER(ctypes.c_int),
	ctypes.POINTER(ctypes.c_int),
	ctypes.POINTER(ctypes.c_uint),
]

libX11.XWarpPointer.restype = ctypes.c_int
libX11.XWarpPointer.argtypes = [
	Display_p,
	Window,
	Window,
	ctypes.c_int,
	ctypes.c_int,
	ctypes.c_uint,
	ctypes.c_uint,
	ctypes.c_int,
	ctypes.c_int,
]

libX11.XFlush.restype = ctypes.c_int
libX11.XFlush.argtypes = [Display_p]

libX11.XCreateFontCursor.restype = Cursor
libX11.XCreateFontCursor.argtypes = [Display_p, ctypes.c_uint]

libX11.XDefineCursor.restype = ctypes.c_int
libX11.XDefineCursor.argtypes = [Display_p, Window, Cursor]

libX11.XUndefineCursor.restype = ctypes.c_int
libX11.XUndefineCursor.argtypes = [Display_p, Window]

libX11.XSelectInput.restype = ctypes.c_int
libX11.XSelectInput.argtypes = [Display_p, Window, ctypes.c_long]

libX11.XStringToKeysym.restype = ctypes.c_ulong
libX11.XStringToKeysym.argtypes = [ctypes.c_char_p]

libX11.XKeysymToKeycode.restype = ctypes.c_uint
libX11.XKeysymToKeycode.argtypes = [Display_p, ctypes.c_ulong]

libX11.XGrabKey.restype = ctypes.c_int
libX11.XGrabKey.argtypes = [Display_p, ctypes.c_int, ctypes.c_uint, Window, Bool, ctypes.c_int, ctypes.c_int]

libX11.XUngrabKey.restype = ctypes.c_int
libX11.XUngrabKey.argtypes = [Display_p, ctypes.c_int, ctypes.c_uint, Window]

libX11.XPending.restype = ctypes.c_int
libX11.XPending.argtypes = [Display_p]

libX11.XNextEvent.restype = ctypes.c_int
libX11.XNextEvent.argtypes = [Display_p, ctypes.POINTER(XEvent)]

libXss.XScreenSaverAllocInfo.restype = ctypes.POINTER(XScreenSaverInfo)
libXss.XScreenSaverAllocInfo.argtypes = []

libXss.XScreenSaverQueryInfo.restype = Status
libXss.XScreenSaverQueryInfo.argtypes = [Display_p, Window, ctypes.POINTER(XScreenSaverInfo)]


class X11Context:
	def __init__(self) -> None:
		self.display: Display_p | None = None
		self.screen: int = 0
		self.root: Window = 0
		self.cursor: Cursor = 0
		self.quit_keycodes: set[int] = set()

	def open(self) -> None:
		if self.display:
			return
		dpy = libX11.XOpenDisplay(None)
		if not dpy:
			raise OSError("Cannot open X11 display. Ensure you are in an X11 session and DISPLAY is set.")
		self.display = dpy
		self.screen = libX11.XDefaultScreen(self.display)
		self.root = libX11.XRootWindow(self.display, self.screen)

		# Prepare quit hotkeys: 'q' and 'Cyrillic_shorti' (й)
		for name in (b"q", b"Cyrillic_shorti"):
			keysym = libX11.XStringToKeysym(name)
			if keysym != 0:
				keycode = libX11.XKeysymToKeycode(self.display, keysym)
				if keycode != 0:
					self.quit_keycodes.add(int(keycode))

		# Listen for key presses on root and grab the quit key(s)
		libX11.XSelectInput(self.display, self.root, KeyPressMask)
		for kc in self.quit_keycodes:
			libX11.XGrabKey(self.display, kc, AnyModifier, self.root, True, GrabModeAsync, GrabModeAsync)

	def close(self) -> None:
		if not self.display:
			return
		# Ungrab keys
		for kc in self.quit_keycodes:
			libX11.XUngrabKey(self.display, kc, AnyModifier, self.root)
		# Restore cursor on root
		try:
			libX11.XUndefineCursor(self.display, self.root)
		except Exception:
			pass
		libX11.XFlush(self.display)
		libX11.XCloseDisplay(self.display)
		self.display = None

	def get_virtual_bounds(self) -> tuple[int, int]:
		assert self.display is not None
		w = libX11.XDisplayWidth(self.display, self.screen)
		h = libX11.XDisplayHeight(self.display, self.screen)
		return int(w), int(h)

	def get_cursor_pos(self) -> tuple[int, int]:
		assert self.display is not None
		root_return = Window()
		child_return = Window()
		root_x = ctypes.c_int()
		root_y = ctypes.c_int()
		win_x = ctypes.c_int()
		win_y = ctypes.c_int()
		mask = ctypes.c_uint()
		libX11.XQueryPointer(
			self.display,
			self.root,
			ctypes.byref(root_return),
			ctypes.byref(child_return),
			ctypes.byref(root_x),
			ctypes.byref(root_y),
			ctypes.byref(win_x),
			ctypes.byref(win_y),
			ctypes.byref(mask),
		)
		return int(root_x.value), int(root_y.value)

	def set_cursor_pos(self, x: int, y: int) -> None:
		assert self.display is not None
		libX11.XWarpPointer(self.display, 0, self.root, 0, 0, 0, 0, int(x), int(y))
		libX11.XFlush(self.display)

	def force_arrow_cursor(self) -> None:
		"""Set the root window cursor to an arrow. Note: other windows may override this."""
		assert self.display is not None
		self.cursor = libX11.XCreateFontCursor(self.display, XC_left_ptr)
		libX11.XDefineCursor(self.display, self.root, self.cursor)
		libX11.XFlush(self.display)

	def restore_cursor(self) -> None:
		assert self.display is not None
		libX11.XUndefineCursor(self.display, self.root)
		libX11.XFlush(self.display)

	def query_idle_ms(self) -> int:
		assert self.display is not None
		info = libXss.XScreenSaverAllocInfo()
		if not info:
			raise OSError("XScreenSaverAllocInfo failed")
		status = libXss.XScreenSaverQueryInfo(self.display, self.root, info)
		if status == 0:
			raise OSError("XScreenSaverQueryInfo failed")
		return int(info.contents.idle)

	def hotkey_quit_pressed(self) -> bool:
		assert self.display is not None
		pressed = False
		while libX11.XPending(self.display) > 0:
			ev = XEvent()
			libX11.XNextEvent(self.display, ctypes.byref(ev))
			if ev.type == KeyPress:
				kc = int(ev.xkey.keycode)
				if kc in self.quit_keycodes:
					pressed = True
		return pressed


def clamp(value: float, min_value: float, max_value: float) -> float:
	return max(min_value, min(value, max_value))


def pick_diagonal_velocity(
		speed_mag: float,
		hit_left: bool,
		hit_right: bool,
		hit_top: bool,
		hit_bottom: bool,
		prev_vx: float = 0.0,
		prev_vy: float = 0.0,
	) -> tuple[float, float]:
	comp = max(1.0, float(speed_mag)) / math.sqrt(2.0)

	def signf(v: float) -> float:
		return 1.0 if v >= 0.0 else -1.0

	prev_speed = math.hypot(prev_vx, prev_vy)
	s_prev = None
	if prev_speed > 1e-6 and abs(abs(prev_vx) - abs(prev_vy)) <= max(1.0, 0.05 * prev_speed):
		s_prev = signf(prev_vy) / signf(prev_vx)

	for _ in range(16):
		candidates = [1.0, -1.0]
		if s_prev is not None:
			candidates = [x for x in candidates if x != s_prev] + [s_prev]
		else:
			random.shuffle(candidates)

		for s in candidates:
			hx = 1.0 if hit_left else (-1.0 if hit_right else None)
			hy = 1.0 if hit_top else (-1.0 if hit_bottom else None)

			if hx is None and hy is None:
				hx_try = random.choice([-1.0, 1.0])
				hy_try = s * hx_try
			elif hx is None and hy is not None:
				hx_try = hy / s
				hy_try = hy
			elif hx is not None and hy is None:
				hx_try = hx
				hy_try = s * hx
			else:
				hx_try = hx
				hy_try = hy
				if abs((hy_try / hx_try) - s) > 0.1:
					continue

			vx = hx_try * comp
			vy = hy_try * comp

			if prev_speed > 1e-6:
				cos_sim = (prev_vx * vx + prev_vy * vy) / (prev_speed * comp)
				if cos_sim <= -0.2:
					continue

			return vx, vy

	# Fallback
	hx = 1.0 if hit_left else (-1.0 if hit_right else random.choice([-1.0, 1.0]))
	hy = 1.0 if hit_top else (-1.0 if hit_bottom else random.choice([-1.0, 1.0]))
	return hx * comp, hy * comp


def run_cursor_screensaver(xc: X11Context, animation_fps: float = 120.0) -> None:
	"""Animate cursor diagonally with edge angle changes until real input/hotkey."""
	idle_prev_ms = xc.query_idle_ms()
	width, height = xc.get_virtual_bounds()
	min_x = 0.0
	min_y = 0.0
	max_x = float(width - 1)
	max_y = float(height - 1)

	start_x, start_y = xc.get_cursor_pos()
	pos_x: float = float(start_x)
	pos_y: float = float(start_y)

	# Try to enforce arrow cursor on root (note: other windows may override)
	xc.force_arrow_cursor()

	speed = random.uniform(300.0, 700.0)
	vel_x, vel_y = pick_diagonal_velocity(speed, False, False, False, False)

	frame_dt = 1.0 / max(30.0, float(animation_fps))
	prev_t = time.perf_counter()

	try:
		while True:
			if xc.hotkey_quit_pressed():
				sys.exit(0)

			idle_ms = xc.query_idle_ms()
			# Real input resets idle to a small value; detect decrease
			if idle_ms + 50 < idle_prev_ms:
				break
			idle_prev_ms = idle_ms

			now = time.perf_counter()
			dt = max(0.0, min(0.05, now - prev_t))
			prev_t = now

			pos_x += vel_x * dt
			pos_y += vel_y * dt

			hit_left = pos_x < min_x
			hit_right = pos_x > max_x
			hit_top = pos_y < min_y
			hit_bottom = pos_y > max_y
			if hit_left or hit_right or hit_top or hit_bottom:
				pos_x = clamp(pos_x, min_x, max_x)
				pos_y = clamp(pos_y, min_y, max_y)
				if hit_left:
					pos_x = min_x + 1.0
				if hit_right:
					pos_x = max_x - 1.0
				if hit_top:
					pos_y = min_y + 1.0
				if hit_bottom:
					pos_y = max_y - 1.0

				speed_mag = max(150.0, math.hypot(vel_x, vel_y))
				vel_x, vel_y = pick_diagonal_velocity(speed_mag, hit_left, hit_right, hit_top, hit_bottom, vel_x, vel_y)

			xc.set_cursor_pos(int(round(pos_x)), int(round(pos_y)))
			time.sleep(frame_dt)
	finally:
		xc.restore_cursor()


def get_idle_seconds(xc: X11Context) -> float:
	return xc.query_idle_ms() / 1000.0


def monitor_idle_and_run(xc: X11Context, threshold_seconds: int) -> None:
	print(f"MousWalk (Linux) armed. Will start after {threshold_seconds} seconds of inactivity.")
	print("Press Q to quit at any time.")
	try:
		while True:
			if xc.hotkey_quit_pressed():
				sys.exit(0)
			idle_s = get_idle_seconds(xc)
			if idle_s >= threshold_seconds:
				run_cursor_screensaver(xc, animation_fps=120.0)
				time.sleep(0.25)
			else:
				time.sleep(1.0)
	except KeyboardInterrupt:
		print("\nExiting.")


def parse_args(argv: list[str]) -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Transparent cursor screensaver for Linux (X11)",
		formatter_class=argparse.ArgumentDefaultsHelpFormatter,
	)
	parser.add_argument(
		"--minutes",
		type=float,
		default=10.0,
		help="Idle minutes before the cursor animation starts",
	)
	return parser.parse_args(argv)


def main(argv: list[str]) -> int:
	xc = X11Context()
	xc.open()
	try:
		args = parse_args(argv)
		threshold_seconds = max(1, int(args.minutes * 60.0))
		# Start immediately, then arm for idle threshold
		run_cursor_screensaver(xc, animation_fps=120.0)
		monitor_idle_and_run(xc, threshold_seconds)
		return 0
	finally:
		xc.close()


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
