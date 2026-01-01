import logging
import re
from typing import Any

from scraper_backend.scrapers.actions.base import BaseAction
from scraper_backend.scrapers.actions.registry import ActionRegistry
from scraper_backend.scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)


@ActionRegistry.register("process_images")
class ProcessImagesAction(BaseAction):
    """Action to process, filter, and upgrade image URLs."""

    def execute(self, params: dict[str, Any]) -> None:
        field = params.get("field")
        if not field:
            raise WorkflowExecutionError("Process_images requires 'field' parameter")

        images = self.executor.results.get(field)
        if not images:
            logger.warning(f"No images found in field {field}")
            return

        if not isinstance(images, list):
            images = [images]

        # 1. Quality Upgrades (URL Transformation)
        upgrade_patterns = params.get("quality_patterns", [])
        processed_images = []

        for img_url in images:
            if not img_url:
                continue

            new_url = img_url
            for pattern in upgrade_patterns:
                regex = pattern.get("regex")
                replacement = pattern.get("replacement")
                if regex and replacement:
                    try:
                        new_url = re.sub(regex, replacement, new_url)
                    except Exception as e:
                        logger.warning(f"Regex error in image upgrade: {e}")

            processed_images.append(new_url)

        # 2. Filtering
        filters = params.get("filters", [])
        filtered_images = []
        for img_url in processed_images:
            keep = True
            for filter_rule in filters:
                if filter_rule.get("type") == "exclude_text":
                    text = filter_rule.get("text")
                    if text and text in img_url:
                        keep = False
                        break
                elif filter_rule.get("type") == "require_text":
                    text = filter_rule.get("text")
                    if text and text not in img_url:
                        keep = False
                        break
            if keep:
                filtered_images.append(img_url)

        # 3. Deduplication
        if params.get("deduplicate", True):
            seen = set()
            unique_images = []
            for img in filtered_images:
                if img not in seen:
                    seen.add(img)
                    unique_images.append(img)
            filtered_images = unique_images

        self.executor.results[field] = filtered_images
        logger.debug(f"Processed images for {field}: {len(filtered_images)} remaining")
