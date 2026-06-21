from app.discovery.agent_discovery_system import EnhancedAgentDiscoverySystem
from app.core.config import settings
api_key = settings.DASHSCOPE_API_KEY
AgentDiscovery = EnhancedAgentDiscoverySystem(api_key=api_key)