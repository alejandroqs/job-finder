import os
import sys
import yaml
import time
from typing import List, Dict, Literal
from pydantic import BaseModel, Field

try:
    from google import genai
    from google.genai import types
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False

from job_finder.interfaces import BaseAIValidator, ParsedAnnouncement


class JobOfferValidation(BaseModel):
    """Structured output schema for Gemini job classification."""
    is_tech_job: bool = Field(
        description="True if the text is a real IT/Software/ICT job opening or employment pool. False otherwise."
    )
    job_title: str | None = Field(
        default=None,
        description="Title of the position (e.g., Técnico de Sistemas). Null if not a valid offer."
    )
    organism: str | None = Field(
        default=None,
        description="The issuing organism (e.g., Ayuntamiento, Ministerio)."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="Confidence level in the classification."
    )


class GeminiValidator(BaseAIValidator):
    """Concrete implementation of BaseAIValidator using Gemini Flash 3.5 via API Studio."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        
        if not SDK_AVAILABLE:
            self.enabled = False
            print("⚠️ AI validation disabled: google-genai package is not available.", file=sys.stderr)
        elif not self.api_key:
            self.enabled = False
            print("⚠️ AI validation disabled: No GEMINI_API_KEY found.", file=sys.stderr)
        else:
            self.enabled = True
            try:
                self.client = genai.Client(api_key=self.api_key)
                prompts = self._load_prompts()
                self.system_prompt = prompts.get("system_prompt", "")
                self.user_prompt_template = prompts.get("user_prompt_template", "")
            except Exception as e:
                self.enabled = False
                print(f"⚠️ AI validation disabled: Failed to initialize client or load prompts: {e}", file=sys.stderr)

    def _load_prompts(self) -> dict:
        yaml_path = os.path.join(os.path.dirname(__file__), "config_prompts.yaml")
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"⚠️ Error loading prompt configuration from {yaml_path}: {e}", file=sys.stderr)
            return {
                "system_prompt": "You are an IT job classifier. Determine if the text is a real IT job opening.",
                "user_prompt_template": "<context>\n{extracted_text}\n</context>\n<task>\nIs this a tech job?\n</task>"
            }

    def validate_batch(self, announcements: List[ParsedAnnouncement]) -> List[ParsedAnnouncement]:
        """
        Validates a batch of announcements and returns only the relevant ones.
        If validation is unavailable or fails, returns the full list unchanged with a warning.
        """
        if not self.enabled:
            print("⚠️ AI validation skipped: Validator not active or missing API key.", file=sys.stderr)
            return announcements

        if not announcements:
            return announcements

        try:
            # 1. Deduplication step: group announcements by URL.
            unique_announcements: List[ParsedAnnouncement] = []
            url_to_announcements: Dict[str, List[ParsedAnnouncement]] = {}
            
            for ann in announcements:
                url = ann.url or ""
                if url not in url_to_announcements:
                    url_to_announcements[url] = []
                    unique_announcements.append(ann)
                url_to_announcements[url].append(ann)

            # Initialize all deduplicated URLs as True (YES) by default to prefer false positives on failure (recall-bias).
            verdict_by_url = {ann.url: True for ann in unique_announcements}
            num_unique = len(unique_announcements)

            # 2. Sequential Validation with Rate Limiting
            for idx, ann in enumerate(unique_announcements):
                validation_result = self._validate_single(ann)
                
                if validation_result is not None:
                    verdict_by_url[ann.url] = validation_result.is_tech_job
                    print(
                        f"🤖 AI Val ({idx + 1}/{num_unique}): {ann.organism} -> "
                        f"is_tech_job={validation_result.is_tech_job} "
                        f"(conf: {validation_result.confidence}, title: {validation_result.job_title})",
                        file=sys.stderr
                    )
                else:
                    # Result is None due to error, defaults to True (YES)
                    print(
                        f"⚠️ AI Val ({idx + 1}/{num_unique}) failed. Keeping by default (recall-bias).",
                        file=sys.stderr
                    )

                # Sleep 12 seconds between calls to stay under the 5-10 RPM limit (Option A)
                # Avoid sleeping after the last unique item
                if idx < num_unique - 1:
                    time.sleep(12.0)

            # 3. Map YES verdicts back to the full list.
            kept_urls = {url for url, verdict in verdict_by_url.items() if verdict}
            final_announcements = [ann for ann in announcements if ann.url in kept_urls]
            return final_announcements

        except Exception as e:
            print(f"⚠️ AI validation failed: {e}. Gracefully keeping all announcements.", file=sys.stderr)
            return announcements

    def _validate_single(self, ann: ParsedAnnouncement) -> JobOfferValidation | None:
        if not self.enabled:
            return None

        desc = ann.description
        if len(desc) > 1500:
            desc = desc[:1500] + "..."

        # Simple and safe string replacement to avoid KeyError from curly braces in source text
        formatted_prompt = self.user_prompt_template.replace("{extracted_text}", desc)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model="gemini-3.5-flash",
                    contents=formatted_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self.system_prompt,
                        response_mime_type="application/json",
                        response_schema=JobOfferValidation,
                        thinking_config=types.ThinkingConfig(thinking_budget=0)
                    )
                )

                if not response.text:
                    raise ValueError("Model returned empty response text")

                result = JobOfferValidation.model_validate_json(response.text)
                return result

            except Exception as e:
                # Handle 429 Too Many Requests (Rate limit)
                is_429 = False
                if hasattr(e, "code") and getattr(e, "code") == 429:
                    is_429 = True
                elif hasattr(e, "status_code") and getattr(e, "status_code") == 429:
                    is_429 = True
                elif "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    is_429 = True

                if is_429:
                    print(
                        f"⏳ API rate limit (429) reached. Sleeping for 60 seconds before retrying "
                        f"(attempt {attempt + 1}/{max_retries})...",
                        file=sys.stderr
                    )
                    time.sleep(60.0)
                else:
                    print(
                        f"⚠️ Error during Gemini validation attempt {attempt + 1}: {e}",
                        file=sys.stderr
                    )
                    if attempt < max_retries - 1:
                        time.sleep(2.0)

        return None
