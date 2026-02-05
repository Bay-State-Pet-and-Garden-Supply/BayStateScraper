"""
CAPTCHA solving service integration for anti-detection manager.
Supports multiple CAPTCHA solving services including 2Captcha, Anti-Captcha, etc.
"""

from __future__ import annotations


import logging
import time
from enum import Enum
from typing import Any

import requests  # type: ignore


# Selenium imports removed - migrated to Playwright
# The By class is no longer used - Playwright uses CSS selectors directly via page.locator()
# Keeping this stub class for backwards compatibility with any remaining Selenium-style code
class By:
    """Stub class for Selenium By selectors - Playwright uses page.locator() with CSS selectors."""

    CSS_SELECTOR = "css selector"
    ID = "id"
    NAME = "name"
    XPATH = "xpath"
    CLASS_NAME = "class name"
    TAG_NAME = "tag name"
    LINK_TEXT = "link text"
    PARTIAL_LINK_TEXT = "partial link text"


logger = logging.getLogger(__name__)


class CaptchaType(Enum):
    """Supported CAPTCHA types."""

    RECAPTCHA_V2 = "recaptcha_v2"
    RECAPTCHA_V3 = "recaptcha_v3"
    HCAPTCHA = "hcaptcha"
    IMAGE_CAPTCHA = "image_captcha"  # Amazon-style image CAPTCHA
    UNKNOWN = "unknown"


class CaptchaService(Enum):
    """Supported CAPTCHA solving services."""

    TWOCAPTCHA = "2captcha"
    ANTICAPTCHA = "anti-captcha"
    CAPSOLVER = "capsolver"


from pydantic import BaseModel, Field


class CaptchaSolverConfig(BaseModel):
    """Configuration for CAPTCHA solving services."""

    enabled: bool = Field(False, description="Enable external CAPTCHA solving")
    service: str = Field("2captcha", description="Solving service (2captcha, anti-captcha, etc.)")
    api_key: str = Field("", description="API key for the service")
    timeout: int = Field(120, description="Timeout in seconds")
    polling_interval: float = Field(5.0, description="Polling interval in seconds")
    max_retries: int = Field(3, description="Max retries for solving")

    @property
    def service_enum(self) -> CaptchaService:
        """Get service as Enum."""
        try:
            return CaptchaService(self.service.lower())
        except ValueError:
            return CaptchaService.TWOCAPTCHA


class CaptchaSolver:
    """
    Handles CAPTCHA solving using external services.

    Supports multiple CAPTCHA types and solving services with automatic
    detection, submission, and solution application.
    """

    def __init__(self, config: CaptchaSolverConfig):
        self.config = config
        self.session = requests.Session()

        # Service endpoints
        self.endpoints = {
            CaptchaService.TWOCAPTCHA: {
                "submit": "http://2captcha.com/in.php",
                "retrieve": "http://2captcha.com/res.php",
            },
            CaptchaService.ANTICAPTCHA: {
                "submit": "https://api.anti-captcha.com/createTask",
                "retrieve": "https://api.anti-captcha.com/getTaskResult",
            },
            CaptchaService.CAPSOLVER: {
                "submit": "https://api.capsolver.com/createTask",
                "retrieve": "https://api.capsolver.com/getTaskResult",
            },
        }

    def solve_captcha(self, driver, url: str) -> bool:
        """
        Main method to solve CAPTCHA on current page.

        Args:
            driver: Selenium WebDriver instance
            url: Current page URL

        Returns:
            True if CAPTCHA was solved successfully, False otherwise
        """
        if not self.config.enabled or not self.config.api_key:
            logger.warning("CAPTCHA solver not configured or disabled")
            return False

        try:
            # Detect CAPTCHA type and extract parameters
            captcha_type, params = self._detect_captcha(driver, url)
            if captcha_type == CaptchaType.UNKNOWN:
                logger.warning("Unknown CAPTCHA type detected")
                return False

            # Submit to solving service
            task_id = self._submit_captcha(captcha_type, params, url)
            if not task_id:
                logger.error("Failed to submit CAPTCHA to solving service")
                return False

            # Wait for and retrieve solution
            solution = self._wait_for_solution(task_id)
            if not solution:
                logger.error("Failed to get CAPTCHA solution")
                return False

            # Apply solution to page
            return self._apply_solution(driver, captcha_type, solution, params)

        except Exception as e:
            logger.error(f"CAPTCHA solving failed: {e}")
            return False

    def _detect_captcha(self, driver, url: str) -> tuple[CaptchaType, dict[str, Any]]:
        """
        Detect CAPTCHA type and extract required parameters.

        Returns:
            Tuple of (captcha_type, parameters_dict)
        """
        try:
            # Check for reCAPTCHA v2
            recaptcha_v2_selectors = [
                ".g-recaptcha",
                "[data-sitekey]",
                ".recaptcha-checkbox",
            ]

            for selector in recaptcha_v2_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        element = elements[0]
                        site_key = element.get_attribute("data-sitekey") or driver.execute_script(
                            """
                                var recaptcha = document.querySelector('.g-recaptcha');
                                if (recaptcha) {
                                    return recaptcha.getAttribute('data-sitekey');
                                }
                                return null;
                            """
                        )
                        if site_key:
                            return CaptchaType.RECAPTCHA_V2, {
                                "site_key": site_key,
                                "element": element,
                            }
                except Exception:
                    continue

            # Check for reCAPTCHA v3
            try:
                recaptcha_v3_script = driver.find_elements(By.CSS_SELECTOR, "script[src*='recaptcha/api.js']")
                if recaptcha_v3_script:
                    # Look for site key in script or global variables
                    site_key = driver.execute_script("""
                        if (window.grecaptcha && window.grecaptcha.render) {
                            // Try to find site key from rendered widgets
                            var widgets = document.querySelectorAll('[data-sitekey]');
                            if (widgets.length > 0) {
                                return widgets[0].getAttribute('data-sitekey');
                            }
                        }
                        return null;
                    """)
                    if site_key:
                        return CaptchaType.RECAPTCHA_V3, {
                            "site_key": site_key,
                        }
            except Exception:
                pass

            # Check for hCaptcha
            hcaptcha_selectors = [
                ".h-captcha",
                "[data-sitekey]",
                ".hcaptcha-checkbox",
            ]

            for selector in hcaptcha_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        element = elements[0]
                        site_key = element.get_attribute("data-sitekey")
                        if site_key:
                            return CaptchaType.HCAPTCHA, {
                                "site_key": site_key,
                                "element": element,
                            }
                except Exception:
                    continue

            # Check for Amazon-style image CAPTCHA
            amazon_captcha_selectors = [
                "form[action*='validateCaptcha']",
                "#captchacharacters",
                "img[src*='captcha']",
                ".a-box-inner form[action*='errors/validateCaptcha']",
            ]

            for selector in amazon_captcha_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        # Try to find the CAPTCHA image
                        captcha_img = driver.find_elements(By.CSS_SELECTOR, "img[src*='captcha'], img.cvf-captcha-img")
                        img_url = captcha_img[0].get_attribute("src") if captcha_img else None
                        return CaptchaType.IMAGE_CAPTCHA, {
                            "image_url": img_url,
                            "form_action": elements[0].get_attribute("action") if elements else None,
                            "is_amazon": True,
                        }
                except Exception:
                    continue

            return CaptchaType.UNKNOWN, {}

        except Exception as e:
            logger.error(f"CAPTCHA detection failed: {e}")
            return CaptchaType.UNKNOWN, {}

    def _submit_captcha(self, captcha_type: CaptchaType, params: dict[str, Any], url: str) -> str | None:
        """
        Submit CAPTCHA to solving service.

        Returns:
            Task ID if successful, None otherwise
        """
        try:
            service = self.config.service_enum
            if service == CaptchaService.TWOCAPTCHA:
                return self._submit_2captcha(captcha_type, params, url)
            elif service == CaptchaService.ANTICAPTCHA:
                return self._submit_anti_captcha(captcha_type, params, url)
            elif service == CaptchaService.CAPSOLVER:
                return self._submit_capsolver(captcha_type, params, url)
            else:
                logger.error(f"Unsupported CAPTCHA service: {self.config.service}")
                return None

        except Exception as e:
            logger.error(f"CAPTCHA submission failed: {e}")
            return None

    def _submit_2captcha(self, captcha_type: CaptchaType, params: dict[str, Any], url: str) -> str | None:
        """Submit CAPTCHA to 2Captcha service."""
        # Handle Amazon image CAPTCHA
        if captcha_type == CaptchaType.IMAGE_CAPTCHA:
            image_url = params.get("image_url")
            if not image_url:
                logger.error("No image URL for image CAPTCHA")
                return None

            data = {
                "key": self.config.api_key,
                "method": "base64" if image_url.startswith("data:") else "post",
                "json": 1,
            }

            if image_url.startswith("data:"):
                # Base64 encoded image
                import base64

                data["body"] = image_url.split(",")[1] if "," in image_url else image_url
            else:
                # URL to image
                data["method"] = "post"
                # Download image and send as base64
                try:
                    img_response = self.session.get(image_url)
                    import base64

                    data["body"] = base64.b64encode(img_response.content).decode("utf-8")
                    data["method"] = "base64"
                except Exception as e:
                    logger.error(f"Failed to download CAPTCHA image: {e}")
                    return None

            response = self.session.post(self.endpoints[CaptchaService.TWOCAPTCHA]["submit"], data=data)
            result = response.json()

            if result.get("status") == 1:
                return cast(str, result.get("request"))
            else:
                logger.error(f"2Captcha image submission failed: {result}")
                return None

        # Standard reCAPTCHA/hCaptcha handling
        data = {
            "key": self.config.api_key,
            "method": "userrecaptcha",
            "googlekey": params.get("site_key", ""),
            "pageurl": url,
            "json": 1,
        }

        if captcha_type == CaptchaType.RECAPTCHA_V3:
            data["version"] = "v3"
            data["action"] = "verify"  # Default action
        elif captcha_type == CaptchaType.HCAPTCHA:
            data["method"] = "hcaptcha"
            data["sitekey"] = params.get("site_key", "")

        response = self.session.post(self.endpoints[CaptchaService.TWOCAPTCHA]["submit"], data=data)
        result = response.json()

        if result.get("status") == 1:
            return cast(str, result.get("request"))
        else:
            logger.error(f"2Captcha submission failed: {result}")
            return None

    def _submit_anti_captcha(self, captcha_type: CaptchaType, params: dict[str, Any], url: str) -> str | None:
        """Submit CAPTCHA to Anti-Captcha service."""
        task_data = {
            "type": "RecaptchaV2TaskProxyless",
            "websiteURL": url,
            "websiteKey": params["site_key"],
        }

        if captcha_type == CaptchaType.RECAPTCHA_V3:
            task_data["type"] = "RecaptchaV3TaskProxyless"
            task_data["pageAction"] = "verify"
        elif captcha_type == CaptchaType.HCAPTCHA:
            task_data["type"] = "HCaptchaTaskProxyless"

        data = {
            "clientKey": self.config.api_key,
            "task": task_data,
        }

        response = self.session.post(self.endpoints[CaptchaService.ANTICAPTCHA]["submit"], json=data)
        result = response.json()

        if result.get("errorId") == 0:
            return str(result["taskId"])
        else:
            logger.error(f"Anti-Captcha submission failed: {result}")
            return None

    def _submit_capsolver(self, captcha_type: CaptchaType, params: dict[str, Any], url: str) -> str | None:
        """Submit CAPTCHA to CapSolver service."""
        task_data = {
            "type": "ReCaptchaV2TaskProxyLess",
            "websiteURL": url,
            "websiteKey": params["site_key"],
        }

        if captcha_type == CaptchaType.RECAPTCHA_V3:
            task_data["type"] = "ReCaptchaV3TaskProxyLess"
            task_data["pageAction"] = "verify"
        elif captcha_type == CaptchaType.HCAPTCHA:
            task_data["type"] = "HCaptchaTaskProxyLess"

        data = {
            "clientKey": self.config.api_key,
            "appId": "appId",  # CapSolver specific
            "task": task_data,
        }

        response = self.session.post(self.endpoints[CaptchaService.CAPSOLVER]["submit"], json=data)
        result = response.json()

        if result.get("errorId") == 0:
            return cast(str, result["taskId"])
        else:
            logger.error(f"CapSolver submission failed: {result}")
            return None

    def _wait_for_solution(self, task_id: str) -> str | None:
        """
        Wait for CAPTCHA solution from service.

        Returns:
            Solution token if successful, None otherwise
        """
        start_time = time.time()

        while time.time() - start_time < self.config.timeout:
            try:
                solution = self._retrieve_solution(task_id)
                if solution:
                    return solution

                time.sleep(self.config.polling_interval)

            except Exception as e:
                logger.error(f"Solution retrieval failed: {e}")
                time.sleep(self.config.polling_interval)

        logger.error("CAPTCHA solution timeout")
        return None

    def _retrieve_solution(self, task_id: str) -> str | None:
        """Retrieve solution from solving service."""
        try:
            service = self.config.service_enum
            if service == CaptchaService.TWOCAPTCHA:
                return self._retrieve_2captcha(task_id)
            elif service == CaptchaService.ANTICAPTCHA:
                return self._retrieve_anti_captcha(task_id)
            elif service == CaptchaService.CAPSOLVER:
                return self._retrieve_capsolver(task_id)
            else:
                logger.error(f"Unsupported CAPTCHA service: {self.config.service}")
                return None

        except Exception as e:
            logger.error(f"Solution retrieval failed: {e}")
            return None

    def _retrieve_2captcha(self, task_id: str) -> str | None:
        """Retrieve solution from 2Captcha."""
        params = {
            "key": self.config.api_key,
            "action": "get",
            "id": task_id,
            "json": 1,
        }

        response = self.session.get(
            self.endpoints[CaptchaService.TWOCAPTCHA]["retrieve"],
            params=params,  # type: ignore
        )
        result = response.json()

        if result.get("status") == 1:
            return cast(str, result.get("request"))
        elif result.get("request") == "CAPCHA_NOT_READY":
            return None  # Still processing
        else:
            logger.error(f"2Captcha retrieval failed: {result}")
            return None

    def _retrieve_anti_captcha(self, task_id: str) -> str | None:
        """Retrieve solution from Anti-Captcha."""
        data = {
            "clientKey": self.config.api_key,
            "taskId": int(task_id),
        }

        response = self.session.post(self.endpoints[CaptchaService.ANTICAPTCHA]["retrieve"], json=data)
        result = response.json()

        if result.get("errorId") == 0:
            status = result.get("status")
            if status == "ready":
                return cast(str, result["solution"]["gRecaptchaResponse"])
            elif status == "processing":
                return None  # Still processing
            else:
                logger.error(f"Anti-Captcha unexpected status: {status}")
                return None
        else:
            logger.error(f"Anti-Captcha retrieval failed: {result}")
            return None

    def _retrieve_capsolver(self, task_id: str) -> str | None:
        """Retrieve solution from CapSolver."""
        data = {
            "clientKey": self.config.api_key,
            "taskId": task_id,
        }

        response = self.session.post(self.endpoints[CaptchaService.CAPSOLVER]["retrieve"], json=data)
        result = response.json()

        if result.get("errorId") == 0:
            status = result.get("status")
            if status == "ready":
                return cast(str, result["solution"]["gRecaptchaResponse"])
            elif status == "processing":
                return None  # Still processing
            else:
                logger.error(f"CapSolver unexpected status: {status}")
                return None
        else:
            logger.error(f"CapSolver retrieval failed: {result}")
            return None

    def _apply_solution(self, driver, captcha_type: CaptchaType, solution: str, params: dict[str, Any]) -> bool:
        """
        Apply CAPTCHA solution to the page.

        Returns:
            True if solution applied successfully
        """
        try:
            if captcha_type in [CaptchaType.RECAPTCHA_V2, CaptchaType.HCAPTCHA]:
                # Inject the solution into the textarea
                script = f"""
                    var textarea = document.querySelector('textarea[name="g-recaptcha-response"]');
                    if (!textarea) {{
                        textarea = document.createElement('textarea');
                        textarea.name = 'g-recaptcha-response';
                        textarea.style.display = 'none';
                        document.body.appendChild(textarea);
                    }}
                    textarea.value = '{solution}';

                    // Trigger callback if it exists
                    if (window.grecaptchaCallback) {{
                        window.grecaptchaCallback('{solution}');
                    }}

                    // Mark as completed
                    var badge = document.querySelector('.g-recaptcha-badge');
                    if (badge) {{
                        badge.style.display = 'none';
                    }}
                """
                driver.execute_script(script)

            elif captcha_type == CaptchaType.RECAPTCHA_V3:
                # For v3, the token is usually submitted with forms
                # Store it for later use
                driver.execute_script(f"window.recaptchaV3Token = '{solution}';")

            elif captcha_type == CaptchaType.IMAGE_CAPTCHA:
                # For Amazon-style image CAPTCHA, enter the solution into the text field
                try:
                    # Find the CAPTCHA input field
                    captcha_input = driver.find_element(
                        By.CSS_SELECTOR,
                        "#captchacharacters, input[name='captchacharacters'], input[name='field-keywords'], input[type='text'][name*='captcha']",
                    )
                    captcha_input.clear()
                    captcha_input.send_keys(solution)

                    # Find and click the submit button
                    submit_btn = driver.find_element(
                        By.CSS_SELECTOR,
                        "button[type='submit'], input[type='submit'], .a-button-input, button.a-button-text",
                    )
                    submit_btn.click()

                    logger.info("Amazon image CAPTCHA solution submitted")
                    # Wait for page to process
                    import time

                    time.sleep(2)
                except Exception as e:
                    logger.error(f"Failed to apply Amazon CAPTCHA solution: {e}")
                    return False

            logger.info(f"CAPTCHA solution applied for type: {captcha_type.value}")
            return True

        except Exception as e:
            logger.error(f"Failed to apply CAPTCHA solution: {e}")
            return False
