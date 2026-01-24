from app.adapters.ig_client import AsyncIGClient
from app.adapters.gemini_service import GeminiService
from app.adapters.news_client import NewsClient
from app.services.collector import CollectorService
from app.services.market_data import MarketDataService
from app.services.streamer import StreamerService
from app.services.trader import StrategyEngine
from app.services.risk import RiskManager
from app.services.analyzer import MarketAnalyzer
from app.services.executor import TradeExecutor
from app.services.market_status import MarketStatusService
from app.services.watcher import WatcherService
from app.adapters.notification import HomeAssistantNotifier


class Container:
    """
    Manual Dependency Injection Container.
    Centralizes the instantiation and wiring of the application's service graph.
    """

    @staticmethod
    def create_strategy_engine(
        ig_client: AsyncIGClient,
        dry_run: bool = False,
        analyst_mode: bool = False,
    ) -> StrategyEngine:
        """
        Builds and returns a fully wired StrategyEngine stack.
        """
        # 1. Initialize Adapters
        analyst_service = GeminiService()
        news_service = NewsClient()

        # 2. Initialize Services
        collector = CollectorService(ig_client)
        market_data = MarketDataService(ig_client, collector)
        streamer = StreamerService(ig_client)
        market_status = MarketStatusService()

        # 3. Initialize Domain-Level Services
        risk_manager = RiskManager(ig_client)
        analyzer = MarketAnalyzer(market_data, news_service, analyst_service)
        executor = TradeExecutor(ig_client, streamer, market_status, dry_run)

        # 4. Return Orchestrator
        return StrategyEngine(
            analyzer=analyzer,
            risk_manager=risk_manager,
            executor=executor,
            market_status=market_status,
            analyst_mode=analyst_mode,
        )

    @staticmethod
    def create_watcher() -> WatcherService:
        """
        Builds and returns the WatcherService.
        """
        notifier = HomeAssistantNotifier()
        return WatcherService(notifier)
