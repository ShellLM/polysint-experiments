2026-03-15 12:45:22,589 - llm_consortium.orchestrator - ERROR - Automatic response error for hunter-alpha: Provider returned error
# PolySINT Frontend Test Suite with Playwright

        ## Project Structure

        ```
        tests/
        ├── conftest.py                    # Shared fixtures and configuration
        ├── pages/
        │   ├── base_page.py              # Base page object with common utilities
        │   ├── dashboard_page.py         # Dashboard-specific page object
        │   └── components/
        │       ├── search_component.py   # Search functionality
        │       ├── watchlist_component.py# Watchlist CRUD operations
        │       └── analysis_modal.py     # AI analysis modal
        ├── factories/
        │   └── market_factory.py         # Typed test data generators
        ├── test_dashboard_core.py        # Core UI functionality
        ├── test_search.py                # Search interaction and rendering
        ├── test_watchlist.py             # Watchlist CRUD and validation
        ├── test_security.py              # Security vulnerability detection
        ├── test_error_handling.py        # API failure modes and recovery
        └── test_analysis.py              # AI analysis modal interactions
        ```

        ## Configuration Files

        ### `pytest.ini`
        ```ini
        [pytest]
        asyncio_mode = auto
        testpaths = tests
        python_files = test_*.py
        python_classes = Test*
        python_functions = test_*
        addopts = 
            -v
            --tb=short
            --strict-markers
            --disable-warnings
            --html=test-reports/report.html
            --self-contained-html
            --timeout=30

        markers =
            smoke: Critical path tests for basic functionality
            security: Security vulnerability detection tests
            regression: Regression prevention tests
            slow: Tests that take >5 seconds to run

        filterwarnings =
            ignore::DeprecationWarning
            ignore::PendingDeprecationWarning

        log_cli = true
        log_cli_level = INFO
        ```

        ### `requirements-test.txt`
        ```txt
        # Core testing framework
        pytest>=7.4.0
        pytest-playwright>=0.4.3
        pytest-asyncio>=0.21.1
        pytest-timeout>=2.2.0

        # Reporting
        pytest-html>=4.1.1
        pytest-sugar>=0.9.7

        # Browser automation
        playwright>=1.40.0

        # Mocking and fixtures
        pytest-mock>=3.12.0
        ```

        ### `test_config.py`
        ```python
        """Test configuration constants."""
        import os
        from pathlib import Path

        BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:9000")
        DEFAULT_TIMEOUT = 10000
        VALID_ETHEREUM_ADDRESS = "0x" + "a" * 40
        INVALID_ETHEREUM_ADDRESSES = [
            "invalid",
            "0x" + "g" * 40,    # Non-hex characters
            "0x" + "a" * 39,    # Too short
            "0x" + "a" * 41,    # Too long
            "",
            "0x" + "A" * 40,    # Uppercase
        ]
        XSS_PAYLOADS = [
            "<script>alert('XSS')</script>",
            "<img src=x onerror=alert('XSS')>",
            "<svg/onload=alert('XSS')>",
            "javascript:alert('XSS')",
        ]
        ```

        ## Core Test Infrastructure

        ### `tests/conftest.py`
        ```python
        import pytest
        import json
        from playwright.sync_api import Page, BrowserContext

        @pytest.fixture(scope="function")
        def page(context: BrowserContext) -> Page:
            """Fresh page with proper isolation and timeouts."""
            p = context.new_page()
            p.set_default_timeout(10000)
            context.clear_cookies()
            context.clear_permissions()
            return p

        @pytest.fixture
        def mock_api(page: Page):
            """Callable fixture for mocking API responses."""
            def _mock(endpoint: str, data=None, status: int = 200, delay: int = 0):
                def handle_route(route):
                    if delay > 0:
                        import time
                        time.sleep(delay / 1000)
                    
                    response_data = json.dumps(data) if data is not None else None
                    headers = {"Content-Type": "application/json"} if data is not None else {}
                    
                    route.fulfill(
                        status=status,
                        headers=headers,
                        body=response_data
                    )
                
                page.route(f"**{endpoint}", handle_route)
            return _mock

        @pytest.fixture
        def valid_market():
            return {
                "id": "12345",
                "question": "Will Bitcoin hit $100k in 2024?",
                "volume": 150000.0,
                "shift": 12.5,
                "current_price": 0.45
            }

        @pytest.fixture
        def null_price_market():
            return {
                "id": "999",
                "question": "Test market null price",
                "volume": 5000,
                "shift": 0.0,
                "current_price": None
            }
        ```

        ### `tests/pages/base_page.py`
        ```python
        from playwright.sync_api import Page, Locator

        class BasePage:
            """Base page object with common utilities."""
            
            def __init__(self, page: Page):
                self.page = page
            
            def navigate(self, url: str):
                self.page.goto(url)
                self.page.wait_for_load_state("networkidle")
            
            def reload(self):
                self.page.reload()
                self.page.wait_for_load_state("networkidle")
        ```

        ### `tests/pages/dashboard_page.py`
        ```python
        from playwright.sync_api import Page
        from tests.pages.base_page import BasePage
        from tests.pages.components.search_component import SearchComponent
        from tests.pages.components.watchlist_component import WatchlistComponent
        from tests.pages.components.analysis_modal import AnalysisModal

        class DashboardPage(BasePage):
            """Dashboard page with component composition."""
            
            def __init__(self, page: Page) -> None:
                super().__init__(page)
                self.search = SearchComponent(page)
                self.watchlist = WatchlistComponent(page)
                self.analysis_modal = AnalysisModal(page)
            
            @property
            def markets_table(self):
                return self.page.locator("#marketsTable")
            
            @property
            def research_toggle(self):
                return self.page.locator("#researchToggle")
            
            def get_market_count(self) -> int:
                return self.page.locator("#marketsTable tbody tr").count()
            
            def has_anomaly_badge(self) -> bool:
                return self.page.locator("text=ANOMALY").count() > 0
            
            def toggle_research(self, enabled: bool) -> None:
                if enabled:
                    self.research_toggle.check()
                else:
                    self.research_toggle.uncheck()
            
            def is_research_enabled(self) -> bool:
                return self.research_toggle.is_checked()
        ```

        ### `tests/pages/components/search_component.py`
        ```python
        from playwright.sync_api import Page, Locator
        from tests.pages.base_page import BasePage

        class SearchComponent(BasePage):
            """Single responsibility: only search interactions."""
            
            @property
            def _search_input(self) -> Locator:
                return self.page.locator("#searchInput")
            
            def search(self, query: str, submit: bool = True) -> None:
                self._search_input.fill(query)
                if submit:
                    self._search_input.press("Enter")
            
            def is_search_focused(self) -> bool:
                return self._search_input.evaluate("el => el === document.activeElement")
        ```

        ### `tests/pages/components/watchlist_component.py`
        ```python
        from playwright.sync_api import Page, Locator
        from tests.pages.base_page import BasePage

        class WatchlistComponent(BasePage):
            """Single responsibility: only watchlist CRUD operations."""
            
            @property
            def _address_input(self) -> Locator:
                return self.page.locator("#newAddress")
            
            @property
            def _label_input(self) -> Locator:
                return self.page.locator("#newLabel")
            
            @property
            def _add_button(self) -> Locator:
                return self.page.locator("button:has-text('Add Target')")
            
            @property
            def _validation_error(self) -> Locator:
                return self.page.locator("#addError")
            
            def add_entry(self, address: str, label: str) -> None:
                self._address_input.fill(address)
                self._label_input.fill(label)
                self._add_button.click()
            
            def get_item_count(self) -> int:
                return self.page.locator("#watchlistTable tbody tr").count()
        ```

        ### `tests/pages/components/analysis_modal.py`
        ```python
        from playwright.sync_api import Page, Locator
        from tests.pages.base_page import BasePage

        class AnalysisModal(BasePage):
            """Single responsibility: AI analysis modal interactions."""
            
            @property
            def _modal(self) -> Locator:
                return self.page.locator("#aiModal")
            
            @property
            def _title(self) -> Locator:
                return self.page.locator("#aiModalTitle")
            
            @property
            def _content(self) -> Locator:
                return self.page.locator("#aiModalContent")
            
            def is_open(self) -> bool:
                return self._modal.is_visible()
            
            def close(self) -> None:
                self.page.keyboard.press("Escape")
            
            def click_analyze_button(self, index: int = 0) -> None:
                self.page.locator("button:has-text('Analyze')").nth(index).click()
        ```

        ## Test Data Factories

        ### `tests/factories/market_factory.py`
        ```python
        from dataclasses import dataclass
        from enum import Enum
        from typing import Optional

        class ShiftCategory(Enum):
            NORMAL = "normal"      # < 5%
            WATCH = "watch"        # 5-10%
            ANOMALY = "anomaly"    # > 10%

        @dataclass(frozen=True)
        class MarketData:
            id: str
            question: str
            volume: int
            shift: float
            current_price: Optional[float]
            
            @property
            def shift_category(self) -> ShiftCategory:
                abs_shift = abs(self.shift)
                if abs_shift > 10:
                    return ShiftCategory.ANOMALY
                elif abs_shift >= 5:
                    return ShiftCategory.WATCH
                return ShiftCategory.NORMAL
            
            def to_dict(self) -> dict:
                return {
                    "id": self.id,
                    "question": self.question,
                    "volume": self.volume,
                    "shift": self.shift,
                    "current_price": self.current_price,
                }

        class MarketFactory:
            @staticmethod
            def create_valid() -> MarketData:
                return MarketData(
                    id="12345",
                    question="Test Market",
                    volume=100000,
                    shift=5.0,
                    current_price=0.5,
                )
            
            @staticmethod
            def create_anomalous() -> MarketData:
                return MarketData(
                    id="anomalous",
                    question="Suspicious market",
                    volume=75000,
                    shift=15.0,
                    current_price=0.85,
                )
            
            @staticmethod
            def create_null_price() -> MarketData:
                return MarketData(
                    id="null-price",
                    question="Market with unknown price",
                    volume=1000,
                    shift=0.0,
                    current_price=None,
                )
        ```

        ## Test Modules

        ### `tests/test_dashboard_core.py`
        ```python
        import pytest
        from playwright.sync_api import Page, expect
        from tests.pages.dashboard_page import DashboardPage

        pytestmark = [pytest.mark.smoke]

        @pytest.fixture
        def dashboard(page: Page) -> DashboardPage:
            return DashboardPage(page)

        class TestDashboardInitialization:
            def test_shows_idle_state_initially(self, dashboard, mock_api, base_url):
                mock_api("/markets", [])
                dashboard.navigate(base_url)
                expect(dashboard.page.locator("text=Intelligence awaiting orders")).to_be_visible()
            
            def test_search_input_is_accessible(self, dashboard, mock_api, base_url):
                mock_api("/markets", [])
                dashboard.navigate(base_url)
                dashboard.search.search("", submit=False)
                assert dashboard.search.is_search_focused()

        class TestMarketLoading:
            def test_load_markets_shows_loading_state(self, dashboard, base_url):
                dashboard.page.route("**/markets", lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='[]',
                    delay=1000
                ))
                dashboard.navigate(base_url)
                dashboard.search.search("test")
                expect(dashboard.page.locator("text=Scanning intelligence feeds")).to_be_visible()
            
            def test_empty_results_show_appropriate_message(self, dashboard, mock_api, base_url):
                mock_api("/markets", [])
                dashboard.navigate(base_url)
                dashboard.search.search("nonexistent_market_xyz123")
                expect(dashboard.page.locator("text=No markets found")).to_be_visible()
        ```

        ### `tests/test_search.py`
        ```python
        import pytest
        from playwright.sync_api import Page, expect
        from tests.pages.dashboard_page import DashboardPage
        from tests.factories.market_factory import MarketFactory

        pytestmark = [pytest.mark.regression]

        @pytest.fixture
        def dashboard(page: Page) -> DashboardPage:
            return DashboardPage(page)

        class TestSearchInteraction:
            def test_search_requires_enter_key(self, dashboard, mock_api, base_url, valid_market):
                mock_api("/markets", [valid_market])
                dashboard.navigate(base_url)
                dashboard.search.search("Bitcoin", submit=False)
                expect(dashboard.page.locator("text=Intelligence awaiting orders")).to_be_visible()

        class TestPriceRendering:
            def test_null_price_displays_na(self, dashboard, mock_api, base_url, null_price_market):
                mock_api("/markets", [null_price_market])
                dashboard.navigate(base_url)
                dashboard.search.search("Test")
                expect(dashboard.page.locator("text=Odds: N/A")).to_be_visible()
                expect(dashboard.page.locator("text=null")).not_to_be_visible()
            
            def test_large_volume_formatted_with_commas(self, dashboard, mock_api, base_url):
                market = MarketFactory.create_valid()
                market.volume = 10000000
                mock_api("/markets", [market.to_dict()])
                dashboard.navigate(base_url)
                dashboard.search.search("Test")
                volume_text = dashboard.page.locator("#marketsTable tbody tr td:nth-child(3)").first.text_content()
                assert "," in volume_text

        class TestAnomalyDetection:
            def test_anomalous_market_shows_badge(self, dashboard, mock_api, base_url):
                market = MarketFactory.create_anomalous()
                mock_api("/markets", [market.to_dict()])
                dashboard.navigate(base_url)
                dashboard.search.search("Anomaly")
                expect(dashboard.page.locator("text=ANOMALY")).to_be_visible()
            
            def test_negative_shift_shows_red_color(self, dashboard, mock_api, base_url):
                market = MarketFactory.create_valid()
                market.shift = -8.3
                mock_api("/markets", [market.to_dict()])
                dashboard.navigate(base_url)
                dashboard.search.search("Negative")
                shift_cell = dashboard.page.locator("#marketsTable tbody tr td:nth-child(2)").first
                expect(shift_cell).to_have_class(/text-red-400/)
        ```

        ### `tests/test_watchlist.py`
        ```python
        import pytest
        from playwright.sync_api import Page, expect
        from tests.pages.dashboard_page import DashboardPage
        from test_config import VALID_ETHEREUM_ADDRESS, INVALID_ETHEREUM_ADDRESSES

        pytestmark = [pytest.mark.security, pytest.mark.regression]

        @pytest.fixture
        def dashboard(page: Page) -> DashboardPage:
            return DashboardPage(page)

        class TestWatchlistValidation:
            def test_rejects_all_invalid_addresses(self, dashboard, base_url):
                dashboard.navigate(base_url)
                for invalid_addr in INVALID_ETHEREUM_ADDRESSES:
                    dashboard.watchlist.add_entry(invalid_addr, "Test Entity")
                    expect(dashboard.watchlist._validation_error).to_be_visible()
                    dashboard.page.fill("#newAddress", "")
                    dashboard.page.fill("#newLabel", "")
            
            def test_accepts_valid_address_format(self, dashboard, mock_api, base_url):
                mock_api("/watchlist", {"status": "success"})
                dashboard.navigate(base_url)
                dashboard.watchlist.add_entry(VALID_ETHEREUM_ADDRESS, "Valid Wallet")
                expect(dashboard.watchlist._validation_error).to_be_hidden()

        class TestWatchlistSecurity:
            def test_xss_in_labels_prevented(self, dashboard, mock_api, base_url):
                from test_config import XSS_PAYLOADS
                for payload in XSS_PAYLOADS:
                    mock_api("/watchlist", [{"address": VALID_ETHEREUM_ADDRESS, "label": payload}])
                    dashboard.navigate(base_url)
                    expect(dashboard.page.locator(f"text={payload}")).to_be_visible()
                    expect(dashboard.page.locator("#watchlistTable script")).to_have_count(0)
                    dashboard.reload()
        ```

        ### `tests/test_security.py`
        ```python
        import pytest
        from playwright.sync_api import Page, expect
        from tests.pages.dashboard_page import DashboardPage
        from test_config import XSS_PAYLOADS

        pytestmark = [pytest.mark.security]

        @pytest.fixture
        def dashboard(page: Page) -> DashboardPage:
            return DashboardPage(page)

        class TestInputValidation:
            def test_oversized_search_query_handled(self, dashboard, mock_api, base_url):
                mock_api("/markets", {"detail": "Search query too long"}, status=400)
                dashboard.navigate(base_url)
                dashboard.search.search("x" * 300)
                expect(dashboard.page.locator("text=Search query too long")).to_be_visible()

        class TestErrorSanitization:
            def test_500_errors_hide_internal_details(self, dashboard, mock_api, base_url):
                error_detail = "Database connection failed at /app/db.py:42\nTraceback..."
                mock_api("/markets", {"detail": error_detail}, status=500)
                dashboard.navigate(base_url)
                dashboard.search.search("test")
                expect(dashboard.page.locator("text=Failed to load markets")).to_be_visible()
                page_content = dashboard.page.content()
                assert ".py:" not in page_content
                assert "Traceback" not in page_content
        ```

        ### `tests/test_analysis.py`
        ```python
        import pytest
        from playwright.sync_api import Page, expect
        from tests.pages.dashboard_page import DashboardPage

        pytestmark = [pytest.mark.regression]

        @pytest.fixture
        def dashboard(page: Page) -> DashboardPage:
            return DashboardPage(page)

        class TestAnalysisModal:
            def test_analyze_button_opens_modal(self, dashboard, mock_api, base_url, valid_market):
                mock_api("/markets", [valid_market])
                dashboard.navigate(base_url)
                dashboard.search.search("Bitcoin")
                mock_api("/markets/*/ai-analysis", {"analysis": "Test analysis", "research_used": False})
                dashboard.analysis_modal.click_analyze_button()
                expect(dashboard.analysis_modal.is_open()).to_be_true()
            
            def test_research_toggle_affects_analysis_request(self, dashboard, mock_api, base_url, valid_market):
                request_urls = []
                dashboard.page.on("request", lambda req: request_urls.append(req.url))
                
                mock_api("/markets", [valid_market])
                dashboard.navigate(base_url)
                dashboard.toggle_research(True)
                dashboard.search.search("Bitcoin")
                
                mock_api("/markets/*/ai-analysis", {"analysis": "Test", "research_used": True})
                dashboard.analysis_modal.click_analyze_button()
                dashboard.page.wait_for_timeout(1000)
                
                analysis_reqs = [u for u in request_urls if "ai-analysis" in u]
                assert any("research=true" in u for u in analysis_reqs)
        ```

        ### `tests/test_error_handling.py`
        ```python
        import pytest
        from playwright.sync_api import Page, expect
        from tests.pages.dashboard_page import DashboardPage

        pytestmark = [pytest.mark.regression]

        @pytest.fixture
        def dashboard(page: Page) -> DashboardPage:
            return DashboardPage(page)

        class TestAPIErrorRecovery:
            def test_retry_button_recovers_from_failure(self, dashboard, mock_api, base_url):
                # First request fails
                mock_api("/markets", {}, status=500)
                dashboard.navigate(base_url)
                dashboard.search.search("test")
                expect(dashboard.page.locator("text=Failed to load")).to_be_visible()
                
                # Second request succeeds
                mock_api("/markets", [{"id": "1", "question": "Recovery test", "volume": 10000, "shift": 0.0, "current_price": 0.5}])
                dashboard.page.click("button:has-text('Retry')")
                expect(dashboard.page.locator("text=Recovery test")).to_be_visible()

        class TestNetworkResilience:
            def test_rapid_search_doesnt_crash(self, dashboard, mock_api, base_url, valid_market):
                mock_api("/markets", [valid_market])
                dashboard.navigate(base_url)
                
                # Rapid fire search queries
                for i in range(5):
                    dashboard.search.search(f"test{i}", submit=True)
                
                expect(dashboard.markets_table).to_be_visible()
        ```

        ## Running the Test Suite

        ```bash
        # Install dependencies
        pip install -r requirements-test.txt
        playwright install chromium

        # Run all tests
        pytest tests/ -v

        # Run specific categories
        pytest tests/ -m smoke -v
        pytest tests/test_security.py -v
        pytest tests/ -m "smoke or security" -v

        # Run with visual feedback (headed mode)
        pytest tests/ --headed --slowmo 500

        # Generate HTML report
        pytest tests/ --html=test-reports/report.html --self-contained-html

        # Run parallel tests (optional)
        pip install pytest-xdist
        pytest tests/ -n auto
        ```

        ## Recommended Frontend Improvements

        For better test maintainability, consider adding `data-testid` attributes to `index.html`:

        ```html
        <!-- Replace CSS selectors with data-testid -->
        <input id="searchInput" data-testid="search-input" ...>
        <div id="marketsTable" data-testid="markets-table" ...>
        <button data-testid="analyze-button" ...>
        ```

        This decouples tests from styling changes and improves long-term maintainability.
