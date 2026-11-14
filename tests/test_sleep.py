import os
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from turzx_nvtop.daemon import SleepGate  # noqa: E402

HOOK = os.path.join(os.path.dirname(__file__), "..", "packaging", "turzx-nvtop-sleep")


class SleepGateTest(unittest.TestCase):
    def test_pidfile_lifecycle(self):
        with tempfile.TemporaryDirectory() as d:
            g = SleepGate(threading.Event(), d)
            g.register()
            self.assertEqual(open(os.path.join(d, "turzx-nvtop.pid")).read(), str(os.getpid()))
            g.mark_blank(True)
            self.assertTrue(os.path.exists(g.blank_marker))
            g.mark_blank(False)
            self.assertFalse(os.path.exists(g.blank_marker))
            g.mark_blank(True)
            g.unregister()
            self.assertEqual(os.listdir(d), [])

    def test_register_clears_a_stale_blank_marker(self):
        with tempfile.TemporaryDirectory() as d:
            g = SleepGate(threading.Event(), d)
            open(g.blank_marker, "w").close()
            g.register()
            self.assertFalse(os.path.exists(g.blank_marker))

    def test_enter_and_leave_wake_the_loop(self):
        wake = threading.Event()
        g = SleepGate(wake, "")
        g.enter()
        self.assertTrue(g.sleeping.is_set() and wake.is_set())
        wake.clear()
        g.leave()
        self.assertFalse(g.sleeping.is_set())
        self.assertTrue(wake.is_set())

    def test_no_runtime_dir_is_harmless(self):
        g = SleepGate(threading.Event(), "")
        self.assertIsNone(g.pidfile)
        g.register()
        g.mark_blank(True)
        g.unregister()

    def test_unwritable_runtime_dir_disables_the_pidfile(self):
        g = SleepGate(threading.Event(), "/nonexistent-dir-for-test")
        g.register()
        self.assertIsNone(g.pidfile)


class HookTest(unittest.TestCase):
    def run_hook(self, *args, pidfiles=None):
        env = dict(os.environ)
        env["TURZX_NVTOP_PIDFILES"] = pidfiles or "/nonexistent/turzx-nvtop.pid"
        return subprocess.run(["sh", HOOK, *args], capture_output=True, text=True, timeout=10, env=env)

    def test_never_fails_and_ignores_other_phases(self):
        for args in (("pre", "suspend"), ("post", "hibernate"), ("bogus",), ()):
            self.assertEqual(self.run_hook(*args).returncode, 0, args)

    def test_does_not_signal_a_foreign_process(self):
        """A pidfile naming some other live process (a reused pid) must be left alone."""
        victim = subprocess.Popen(["sleep", "30"])
        try:
            with tempfile.TemporaryDirectory() as d:
                pf = os.path.join(d, "turzx-nvtop.pid")
                open(pf, "w").write(str(victim.pid))
                self.assertEqual(self.run_hook("pre", "suspend", pidfiles=pf).returncode, 0)
            self.assertIsNone(victim.poll(), "victim was signalled")   # USR1 would have killed `sleep`
        finally:
            victim.kill()

    def test_signals_our_daemon_and_waits_for_the_blank_marker(self):
        """A process whose command line names turzx_nvtop gets USR1; the hook then waits for <pidfile>.blank."""
        script = ("import signal,sys,time,os\n"
                  "pf=sys.argv[1]\n"
                  "signal.signal(signal.SIGUSR1, lambda *a: open(pf+'.blank','w').close())\n"
                  "print('ready',flush=True)\n"
                  "time.sleep(20)\n")
        with tempfile.TemporaryDirectory() as d:
            pf = os.path.join(d, "turzx-nvtop.pid")
            # the marker name 'turzx_nvtop' must appear on the command line, like `python -m turzx_nvtop run`
            p = subprocess.Popen([sys.executable, "-c", script, pf, "turzx_nvtop"], stdout=subprocess.PIPE, text=True)
            try:
                p.stdout.readline()
                open(pf, "w").write(str(p.pid))
                r = self.run_hook("pre", "suspend", pidfiles=pf)
                self.assertEqual(r.returncode, 0)
                self.assertTrue(os.path.exists(pf + ".blank"), "hook returned before the daemon blanked")
            finally:
                p.kill()


if __name__ == "__main__":
    unittest.main()
