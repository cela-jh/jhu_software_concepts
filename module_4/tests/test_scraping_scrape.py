"""
`test_scraping_scrape.py`
Covers scrape.py without ever touching a real browser, subprocess, or
network request: every Selenium/subprocess/urllib call is mocked at the
`scraping.scrape` module boundary. time.sleep is patched to a no-op for
every test in this file so retry/backoff logic can be exercised without
actually waiting.
"""
import subprocess
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest
from selenium.common.exceptions import NoSuchElementException

import scraping.scrape as scrape


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr(scrape.time, "sleep", lambda seconds: None)


# ---------------------------------------------------------------------------
# Small, mostly-pure helpers
# ---------------------------------------------------------------------------

@pytest.mark.web
def test_handle_sigterm_raises_stop_requested():
    with pytest.raises(scrape.StopRequested):
        scrape._handle_sigterm(signum=None, frame=None)


@pytest.mark.web
def test_create_profile_dir_creates_a_real_temp_dir():
    profile_dir = scrape.create_profile_dir()
    try:
        assert Path(profile_dir).is_dir()
    finally:
        scrape.cleanup_profile(profile_dir)


@pytest.mark.web
def test_cleanup_profile_removes_directory(tmp_path):
    profile_dir = tmp_path / "chrome-profile"
    profile_dir.mkdir()
    (profile_dir / "some_file").write_text("x")

    scrape.cleanup_profile(str(profile_dir))

    assert not profile_dir.exists()


@pytest.mark.web
def test_open_chrome_launches_expected_command(monkeypatch):
    popen_calls = []
    monkeypatch.setattr(
        scrape.subprocess, "Popen",
        lambda args, **kwargs: popen_calls.append((args, kwargs)) or "fake_process",
    )

    result = scrape._open_chrome("/usr/bin/chrome", "/tmp/profile")

    assert result == "fake_process"
    args, kwargs = popen_calls[0]
    assert args[0] == "/usr/bin/chrome"
    assert "--user-data-dir=/tmp/profile" in args


@pytest.mark.web
def test_try_debug_endpoint_succeeds_immediately(monkeypatch):
    calls = []
    monkeypatch.setattr(scrape, "urlopen", lambda *a, **kw: calls.append(1))

    scrape._try_debug_endpoint("http://127.0.0.1:9222", retries=5)

    assert len(calls) == 1


@pytest.mark.web
def test_try_debug_endpoint_retries_then_succeeds(monkeypatch):
    attempts = {"count": 0}

    def _fake_urlopen(*a, **kw):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise URLError("not up yet")

    monkeypatch.setattr(scrape, "urlopen", _fake_urlopen)

    scrape._try_debug_endpoint("http://127.0.0.1:9222", retries=5)

    assert attempts["count"] == 3


@pytest.mark.web
def test_try_debug_endpoint_gives_up_after_all_retries(monkeypatch):
    attempts = {"count": 0}

    def _always_fail(*a, **kw):
        attempts["count"] += 1
        raise URLError("never comes up")

    monkeypatch.setattr(scrape, "urlopen", _always_fail)

    scrape._try_debug_endpoint("http://127.0.0.1:9222", retries=3)

    assert attempts["count"] == 3


@pytest.mark.web
def test_init_webdriver_configures_and_returns_driver(monkeypatch):
    created_options = []

    class _FakeOptions:
        def __init__(self):
            self.debugger_address = None
            self.page_load_strategy = None
            self.experimental_options = {}

        def add_experimental_option(self, name, value):
            self.experimental_options[name] = value

    def _fake_chrome_options():
        opts = _FakeOptions()
        created_options.append(opts)
        return opts

    monkeypatch.setattr(scrape.webdriver, "ChromeOptions", _fake_chrome_options)
    monkeypatch.setattr(scrape.webdriver, "Chrome", lambda options: ("fake_driver", options))

    driver, used_options = scrape._init_webdriver("127.0.0.1:9222")

    assert driver == "fake_driver"
    assert used_options is created_options[0]
    assert used_options.debugger_address == "127.0.0.1:9222"
    assert used_options.page_load_strategy == "eager"


@pytest.mark.web
def test_terminate_process_normal_exit():
    terminated = []
    fake_process = SimpleNamespace(
        terminate=lambda: terminated.append("terminate"),
        wait=lambda timeout=None: terminated.append("wait"),
        kill=lambda: terminated.append("kill"),
    )

    scrape.terminate_process(fake_process)

    assert terminated == ["terminate", "wait"]


@pytest.mark.web
def test_terminate_process_force_kills_on_timeout():
    events = []

    def _wait(timeout=None):
        if "kill" not in events:
            events.append("wait-timeout")
            raise subprocess.TimeoutExpired(cmd="chrome", timeout=timeout)
        events.append("wait-after-kill")

    fake_process = SimpleNamespace(
        terminate=lambda: events.append("terminate"),
        wait=_wait,
        kill=lambda: events.append("kill"),
    )

    scrape.terminate_process(fake_process)

    assert events == ["terminate", "wait-timeout", "kill", "wait-after-kill"]


@pytest.mark.web
def test_wait_for_cloudflare_clears_immediately():
    fake_driver = SimpleNamespace(title="GradCafe Survey Results")

    scrape._wait_for_cloudflare(fake_driver, timeout=10, poll_interval=1)  # must not raise


@pytest.mark.web
def test_wait_for_cloudflare_clears_after_polling():
    titles = iter(["Just a moment...", "Just a moment...", "GradCafe Survey Results"])

    class _FakeDriver:
        @property
        def title(self):
            return next(titles)

    scrape._wait_for_cloudflare(_FakeDriver(), timeout=10, poll_interval=1)  # must not raise


@pytest.mark.web
def test_wait_for_cloudflare_raises_after_timeout():
    fake_driver = SimpleNamespace(title="Just a moment...")

    with pytest.raises(TimeoutError):
        scrape._wait_for_cloudflare(fake_driver, timeout=3, poll_interval=1)


@pytest.mark.web
def test_block_ad_trackers_issues_expected_cdp_commands():
    calls = []
    fake_driver = SimpleNamespace(execute_cdp_cmd=lambda cmd, params: calls.append((cmd, params)))

    scrape._block_ad_trackers(fake_driver)

    assert calls[0][0] == "Network.enable"
    assert calls[1][0] == "Network.setBlockedURLs"
    assert calls[1][1]["urls"] == scrape.AD_TRACKER_URL_PATTERNS


@pytest.mark.web
def test_check_robots_allowed_true(monkeypatch):
    robots_txt = b"User-agent: *\nAllow: /survey\n"
    monkeypatch.setattr(scrape, "urlopen", lambda request: _FakeResponse(robots_txt))

    assert scrape.check_robots_allowed("https://www.thegradcafe.com/survey") is True


@pytest.mark.web
def test_check_robots_allowed_false(monkeypatch):
    robots_txt = b"User-agent: *\nDisallow: /survey\n"
    monkeypatch.setattr(scrape, "urlopen", lambda request: _FakeResponse(robots_txt))

    assert scrape.check_robots_allowed("https://www.thegradcafe.com/survey") is False


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@pytest.mark.web
@pytest.mark.parametrize("seconds,expected", [
    (5, "5s"),
    (65, "1m 5s"),
    (3661, "1h 1m 1s"),
])
def test_format_duration(seconds, expected):
    assert scrape.format_duration(seconds) == expected


@pytest.mark.web
def test_parse_args_requires_chrome_binary(monkeypatch):
    monkeypatch.setattr("sys.argv", ["scrape.py"])
    with pytest.raises(SystemExit):
        scrape.parse_args()


@pytest.mark.web
def test_parse_args_defaults(monkeypatch, tmp_path):
    chrome_path = tmp_path / "chrome"
    chrome_path.write_text("")
    monkeypatch.setattr("sys.argv", ["scrape.py", "--chrome_binary", str(chrome_path)])

    args = scrape.parse_args()

    assert args.chrome_binary == chrome_path
    assert args.relative_filepath == scrape.DEFAULT_DATA_FILE
    assert args.num_results is None
    assert args.pull_seen_limit == scrape.PULL_SEEN_LIMIT


# ---------------------------------------------------------------------------
# chrome_helper: mocks its own already-tested sub-functions rather than
# reaching all the way down to raw Selenium/subprocess calls again.
# ---------------------------------------------------------------------------

class _FakeDriverForHelper:
    def __init__(self, get_side_effects, title="GradCafe Survey Results"):
        self._get_side_effects = list(get_side_effects)
        self.title = title
        self.get_calls = []

    def get(self, url):
        self.get_calls.append(url)
        effect = self._get_side_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect


@pytest.fixture
def chrome_helper_mocks(monkeypatch):
    monkeypatch.setattr(scrape, "_open_chrome", lambda chrome_bin, profile_dir: "fake_process")
    monkeypatch.setattr(scrape, "_try_debug_endpoint", lambda host_port: None)
    monkeypatch.setattr(scrape, "_block_ad_trackers", lambda driver: None)
    terminated = []
    monkeypatch.setattr(scrape, "terminate_process", lambda process: terminated.append(process))
    return terminated


@pytest.mark.web
def test_chrome_helper_success_path(monkeypatch, chrome_helper_mocks):
    fake_driver = _FakeDriverForHelper(get_side_effects=[None])
    monkeypatch.setattr(scrape, "_init_webdriver", lambda host_port: fake_driver)

    driver, process = scrape.chrome_helper("http://x", "127.0.0.1:9222", "/chrome", "/profile")

    assert driver is fake_driver
    assert process == "fake_process"
    assert chrome_helper_mocks == []


@pytest.mark.web
def test_chrome_helper_retries_then_succeeds(monkeypatch, chrome_helper_mocks):
    fake_driver = _FakeDriverForHelper(get_side_effects=[RuntimeError("boom"), None])
    monkeypatch.setattr(scrape, "_init_webdriver", lambda host_port: fake_driver)

    driver, process = scrape.chrome_helper(
        "http://x", "127.0.0.1:9222", "/chrome", "/profile", retries=3, base_retry_delay=0
    )

    assert len(fake_driver.get_calls) == 2
    assert chrome_helper_mocks == []


@pytest.mark.web
def test_chrome_helper_exhausts_retries_and_cleans_up(monkeypatch, chrome_helper_mocks):
    fake_driver = _FakeDriverForHelper(get_side_effects=[RuntimeError("a"), RuntimeError("b")])
    monkeypatch.setattr(scrape, "_init_webdriver", lambda host_port: fake_driver)

    with pytest.raises(RuntimeError):
        scrape.chrome_helper(
            "http://x", "127.0.0.1:9222", "/chrome", "/profile", retries=2, base_retry_delay=0
        )

    assert chrome_helper_mocks == ["fake_process"]


@pytest.mark.web
def test_chrome_helper_waits_for_cloudflare_when_shown(monkeypatch, chrome_helper_mocks):
    fake_driver = _FakeDriverForHelper(get_side_effects=[None], title="Just a moment...")
    monkeypatch.setattr(scrape, "_init_webdriver", lambda host_port: fake_driver)
    cloudflare_calls = []
    monkeypatch.setattr(scrape, "_wait_for_cloudflare", lambda driver: cloudflare_calls.append(driver))

    scrape.chrome_helper("http://x", "127.0.0.1:9222", "/chrome", "/profile")

    assert cloudflare_calls == [fake_driver]


# ---------------------------------------------------------------------------
# _get_page
# ---------------------------------------------------------------------------

class _FakeDriverForPage:
    def __init__(self, page_sources, titles=None):
        self._page_sources = list(page_sources)
        self.page_source = self._page_sources[0]
        self._titles = titles or ["GradCafe"] * len(page_sources)
        self.title = self._titles[0]
        self.get_calls = []
        self.refresh_calls = 0

    def get(self, url):
        self.get_calls.append(url)
        self._advance()

    def refresh(self):
        self.refresh_calls += 1
        self._advance()

    def _advance(self):
        index = min(len(self.get_calls) + self.refresh_calls, len(self._page_sources) - 1)
        self.page_source = self._page_sources[index]
        self.title = self._titles[index]


VALID_TABLE_HTML = "<html><body><tbody><tr><td>row</td></tr></tbody></body></html>"
NO_TABLE_HTML = "<html><body>no results table here</body></html>"


@pytest.mark.web
def test_get_page_succeeds_first_try():
    driver = _FakeDriverForPage([VALID_TABLE_HTML])

    soup = scrape._get_page(driver, url="http://x", wait=0)

    assert soup.find("tbody") is not None
    assert driver.get_calls == ["http://x"]


@pytest.mark.web
def test_get_page_retries_when_table_missing_then_succeeds():
    driver = _FakeDriverForPage([NO_TABLE_HTML, VALID_TABLE_HTML])

    soup = scrape._get_page(driver, url=None, wait=0, retries=3, base_retry_delay=0)

    assert soup.find("tbody") is not None
    assert driver.refresh_calls == 1


@pytest.mark.web
def test_get_page_raises_after_exhausting_retries():
    driver = _FakeDriverForPage([NO_TABLE_HTML, NO_TABLE_HTML])

    with pytest.raises(RuntimeError):
        scrape._get_page(driver, url="http://x", wait=0, retries=2, base_retry_delay=0)


@pytest.mark.web
def test_get_page_exits_on_http_error(monkeypatch):
    from urllib.error import HTTPError

    def _raise_http_error(url):
        raise HTTPError(url="http://x", code=403, msg="Forbidden", hdrs=None, fp=None)

    driver = SimpleNamespace(get=_raise_http_error, page_source="", title="")

    with pytest.raises(SystemExit):
        scrape._get_page(driver, url="http://x", wait=0)


# ---------------------------------------------------------------------------
# _click_next_page
# ---------------------------------------------------------------------------

@pytest.mark.web
def test_click_next_page_finds_and_clicks_immediately():
    fake_link = object()
    driver = SimpleNamespace(
        find_element=lambda by, xpath: fake_link,
        execute_script=lambda script, element: None,
        current_url="http://next-page",
    )

    result = scrape._click_next_page(driver)

    assert result == "http://next-page"


@pytest.mark.web
def test_click_next_page_returns_none_when_link_never_found():
    driver = SimpleNamespace(
        find_element=lambda by, xpath: (_ for _ in ()).throw(NoSuchElementException()),
        refresh=lambda: None,
    )

    result = scrape._click_next_page(driver, missing_link_retries=2, missing_link_delay=0)

    assert result is None


@pytest.mark.web
def test_click_next_page_finds_link_after_missing_once():
    attempts = {"count": 0}

    def _find_element(by, xpath):
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise NoSuchElementException()
        return object()

    driver = SimpleNamespace(
        find_element=_find_element,
        refresh=lambda: None,
        execute_script=lambda script, element: None,
        current_url="http://next-page",
    )

    result = scrape._click_next_page(driver, missing_link_retries=3, missing_link_delay=0)

    assert result == "http://next-page"


@pytest.mark.web
def test_click_next_page_retries_on_click_failure_then_succeeds():
    attempts = {"count": 0}

    def _execute_script(script, element):
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("click failed")

    driver = SimpleNamespace(
        find_element=lambda by, xpath: object(),
        execute_script=_execute_script,
        current_url="http://next-page",
    )

    result = scrape._click_next_page(driver, retries=3, base_retry_delay=0)

    assert result == "http://next-page"


@pytest.mark.web
def test_click_next_page_raises_after_exhausting_click_retries():
    driver = SimpleNamespace(
        find_element=lambda by, xpath: object(),
        execute_script=lambda script, element: (_ for _ in ()).throw(RuntimeError("nope")),
    )

    with pytest.raises(RuntimeError):
        scrape._click_next_page(driver, retries=2, base_retry_delay=0)


# ---------------------------------------------------------------------------
# scrape_data: mocks _get_page/_click_next_page directly
# ---------------------------------------------------------------------------

@pytest.mark.web
def test_scrape_data_combines_page_and_next_url(monkeypatch):
    fake_soup = SimpleNamespace(find=lambda tag: SimpleNamespace(find_all=lambda t: ["row1", "row2"]))
    monkeypatch.setattr(scrape, "_get_page", lambda driver, url=None: fake_soup)
    monkeypatch.setattr(scrape, "_click_next_page", lambda driver: "http://next")

    results, next_url = scrape.scrape_data("fake_driver", url="http://x")

    assert results == ["row1", "row2"]
    assert next_url == "http://next"


# ---------------------------------------------------------------------------
# run_scrape: the top-level orchestrator. Every one of its own helpers is
# mocked (each is already covered individually above), so these tests
# verify run_scrape's control flow - pull vs. resume mode, each of the
# three stopping conditions, state save/resume, periodic restart, and
# StopRequested handling - not Selenium/network behavior again.
# ---------------------------------------------------------------------------

@pytest.fixture
def run_scrape_mocks(monkeypatch, tmp_path):
    """Mocks every dependency run_scrape calls, with sane defaults that
    individual tests override via monkeypatch."""
    monkeypatch.setattr(scrape.signal, "signal", lambda sig, handler: None)
    monkeypatch.setattr(scrape, "check_robots_allowed", lambda url: True)
    monkeypatch.setattr(scrape, "create_profile_dir", lambda: "/fake/profile")
    calls = SimpleNamespace(
        terminate_process=[], cleanup_profile=[], save_data=[], save_state=[],
        chrome_helper=[],
    )
    monkeypatch.setattr(scrape, "terminate_process", lambda p: calls.terminate_process.append(p))
    monkeypatch.setattr(scrape, "cleanup_profile", lambda p: calls.cleanup_profile.append(p))
    monkeypatch.setattr(scrape, "save_data", lambda rows, path: calls.save_data.append(rows))
    monkeypatch.setattr(scrape, "save_state", lambda state, path: calls.save_state.append(state))

    def _fake_chrome_helper(*a, **kw):
        proc = f"process-{len(calls.chrome_helper) + 1}"
        calls.chrome_helper.append(proc)
        return SimpleNamespace(), proc

    monkeypatch.setattr(scrape, "chrome_helper", _fake_chrome_helper)
    return calls


def _make_args(tmp_path, chrome_binary_exists=True, num_results=None, pull_seen_limit=1000):
    chrome_binary = tmp_path / "chrome"
    if chrome_binary_exists:
        chrome_binary.write_text("")
    return SimpleNamespace(
        relative_filepath=tmp_path / "applicant_data.json",
        chrome_binary=chrome_binary,
        num_results=num_results,
        pull_seen_limit=pull_seen_limit,
    )


@pytest.mark.web
def test_run_scrape_raises_when_chrome_binary_missing(run_scrape_mocks, tmp_path):
    args = _make_args(tmp_path, chrome_binary_exists=False)

    with pytest.raises(FileNotFoundError):
        scrape.run_scrape(args)


@pytest.mark.web
def test_run_scrape_raises_when_robots_disallow(monkeypatch, run_scrape_mocks, tmp_path):
    monkeypatch.setattr(scrape, "check_robots_allowed", lambda url: False)
    args = _make_args(tmp_path)

    with pytest.raises(PermissionError):
        scrape.run_scrape(args)


@pytest.mark.web
def test_run_scrape_resume_mode_returns_early_when_quota_already_met(monkeypatch, run_scrape_mocks, tmp_path):
    monkeypatch.setattr(scrape, "load_existing_urls", lambda path: {"u1", "u2"})
    args = _make_args(tmp_path, num_results=2)

    scrape.run_scrape(args)

    assert run_scrape_mocks.chrome_helper == []  # never even started Chrome


@pytest.mark.web
def test_run_scrape_pull_mode_stops_on_consecutive_seen(monkeypatch, run_scrape_mocks, tmp_path):
    monkeypatch.setattr(scrape, "load_existing_urls", lambda path: {"seen1", "seen2"})
    monkeypatch.setattr(scrape, "state_path_for", lambda path: tmp_path / "state.json")
    monkeypatch.setattr(scrape, "scrape_data", lambda driver, url=None: ([], "http://next"))
    monkeypatch.setattr(scrape, "clean_data", lambda raw, url: [{"url": "seen1"}, {"url": "seen2"}])
    args = _make_args(tmp_path, num_results=None, pull_seen_limit=2)

    scrape.run_scrape(args)

    assert run_scrape_mocks.save_data == []
    assert run_scrape_mocks.terminate_process == ["process-1"]
    assert run_scrape_mocks.cleanup_profile == ["/fake/profile"]


@pytest.mark.web
def test_run_scrape_pull_mode_stops_when_no_more_pages(monkeypatch, run_scrape_mocks, tmp_path):
    monkeypatch.setattr(scrape, "load_existing_urls", lambda path: set())
    monkeypatch.setattr(scrape, "state_path_for", lambda path: tmp_path / "state.json")
    monkeypatch.setattr(scrape, "scrape_data", lambda driver, url=None: ([], None))
    monkeypatch.setattr(scrape, "clean_data", lambda raw, url: [{"url": "new1"}])
    args = _make_args(tmp_path, num_results=None)

    scrape.run_scrape(args)

    assert run_scrape_mocks.save_data == [[{"url": "new1"}]]
    assert run_scrape_mocks.save_state == []  # pull mode never saves pagination state


@pytest.mark.web
def test_run_scrape_resume_mode_uses_saved_state_and_unlinks_it_when_done(monkeypatch, run_scrape_mocks, tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text('{"next_url": "http://resumed"}')
    monkeypatch.setattr(scrape, "load_existing_urls", lambda path: set())
    monkeypatch.setattr(scrape, "state_path_for", lambda path: state_path)
    monkeypatch.setattr(scrape, "load_state", lambda path: {"next_url": "http://resumed"})

    seen_urls_passed = []
    def _fake_scrape_data(driver, url=None):
        seen_urls_passed.append(url)
        return [], None
    monkeypatch.setattr(scrape, "scrape_data", _fake_scrape_data)
    monkeypatch.setattr(scrape, "clean_data", lambda raw, url: [{"url": "new1"}])
    args = _make_args(tmp_path, num_results=10)

    scrape.run_scrape(args)

    assert seen_urls_passed[0] == "http://resumed"
    assert not state_path.exists()  # unlinked once there were no more pages


@pytest.mark.web
def test_run_scrape_resume_mode_saves_state_and_computes_eta_across_pages(monkeypatch, run_scrape_mocks, tmp_path):
    monkeypatch.setattr(scrape, "load_existing_urls", lambda path: set())
    monkeypatch.setattr(scrape, "state_path_for", lambda path: tmp_path / "state.json")
    monkeypatch.setattr(scrape, "load_state", lambda path: None)

    pages = iter([([], "http://page2"), ([], None)])
    monkeypatch.setattr(scrape, "scrape_data", lambda driver, url=None: next(pages))
    monkeypatch.setattr(scrape, "clean_data", lambda raw, url: [{"url": f"new-{url}"}])
    args = _make_args(tmp_path, num_results=10)

    scrape.run_scrape(args)

    # One save_state call for the middle page (next_url known, quota not yet met).
    assert run_scrape_mocks.save_state == [{"next_url": "http://page2"}]


@pytest.mark.web
def test_run_scrape_resume_mode_breaks_immediately_after_reaching_quota(monkeypatch, run_scrape_mocks, tmp_path):
    monkeypatch.setattr(scrape, "load_existing_urls", lambda path: set())
    monkeypatch.setattr(scrape, "state_path_for", lambda path: tmp_path / "state.json")
    monkeypatch.setattr(scrape, "load_state", lambda path: None)
    monkeypatch.setattr(scrape, "scrape_data", lambda driver, url=None: ([], "http://page2"))
    monkeypatch.setattr(scrape, "clean_data", lambda raw, url: [{"url": "new1"}])
    args = _make_args(tmp_path, num_results=1)

    scrape.run_scrape(args)

    assert run_scrape_mocks.save_state == [{"next_url": "http://page2"}]


@pytest.mark.web
def test_run_scrape_restarts_chrome_periodically(monkeypatch, run_scrape_mocks, tmp_path):
    monkeypatch.setattr(scrape, "RESTART_EVERY_N_PAGES", 1)
    monkeypatch.setattr(scrape, "load_existing_urls", lambda path: set())
    monkeypatch.setattr(scrape, "state_path_for", lambda path: tmp_path / "state.json")

    pages = iter([([], "http://page2"), ([], None)])
    monkeypatch.setattr(scrape, "scrape_data", lambda driver, url=None: next(pages))
    monkeypatch.setattr(scrape, "clean_data", lambda raw, url: [{"url": "new-page"}])
    args = _make_args(tmp_path, num_results=None, pull_seen_limit=1000)

    scrape.run_scrape(args)

    assert run_scrape_mocks.chrome_helper == ["process-1", "process-2"]
    assert "process-1" in run_scrape_mocks.terminate_process  # restarted mid-loop
    assert run_scrape_mocks.terminate_process[-1] == "process-2"  # and cleaned up at the end


@pytest.mark.web
def test_run_scrape_handles_stop_requested_cleanly(monkeypatch, run_scrape_mocks, tmp_path):
    monkeypatch.setattr(scrape, "load_existing_urls", lambda path: set())
    monkeypatch.setattr(scrape, "state_path_for", lambda path: tmp_path / "state.json")

    def _raise_stop(driver, url=None):
        raise scrape.StopRequested()

    monkeypatch.setattr(scrape, "scrape_data", _raise_stop)
    args = _make_args(tmp_path, num_results=None)

    scrape.run_scrape(args)  # must not raise

    assert run_scrape_mocks.terminate_process == ["process-1"]
    assert run_scrape_mocks.cleanup_profile == ["/fake/profile"]
