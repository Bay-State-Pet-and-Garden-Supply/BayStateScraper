"""
Browser-use compatibility wrapper for langchain-openai.

This module provides a compatibility layer between browser-use and newer versions
of langchain-openai that don't expose the 'provider' attribute required by
browser-use Agent initialization.

Usage:
    from utils.llm_wrappers import ChatOpenAI

    llm = ChatOpenAI(model="gpt-4o-mini")
    agent = Agent(task="...", llm=llm)
"""

from langchain_openai import ChatOpenAI as BaseChatOpenAI


class ChatOpenAI(BaseChatOpenAI):
    """
    Wrapper around langchain_openai.ChatOpenAI that adds the 'provider' attribute.

    browser-use's Agent class checks for llm.provider during initialization.
    Newer versions of langchain-openai (1.x+) use Pydantic v2 models which don't
    expose this attribute, causing AttributeError.

    This wrapper adds the provider property to ensure compatibility.
    """

    @property
    def provider(self) -> str:
        """Return the provider name for browser-use compatibility."""
        return "openai"
