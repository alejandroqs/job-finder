import os
import sys
import yaml
import time
import json
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


class JobOfferValidationItem(BaseModel):
    """Item verdict representing classification of a single job within a batch."""
    id: int = Field(description="The index/id of the job from the input list.")
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
    reason: str | None = Field(
        default=None,
        description="Reason/rationale for this verdict."
    )


class JobOfferValidationBatch(BaseModel):
    """Structured output schema for a batch of Gemini job classifications."""
    results: List[JobOfferValidationItem] = Field(
        description="List of validation results matching the input IDs."
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
                "user_prompt_template": "<context>\n{jobs_json}\n</context>\n<task>\nAnalyze the jobs and return results.\n</task>"
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

            # Slice unique announcements into chunks of 10
            chunk_size = 10
            chunks = [unique_announcements[i:i + chunk_size] for i in range(0, num_unique, chunk_size)]
            
            # Execute validation for each chunk in parallel using ThreadPoolExecutor
            from concurrent.futures import ThreadPoolExecutor
            results_by_chunk = [None] * len(chunks)
            
            def validate_and_store(chunk_idx: int, chunk_list: List[ParsedAnnouncement]):
                results_by_chunk[chunk_idx] = self._validate_chunk(chunk_list)

            with ThreadPoolExecutor(max_workers=len(chunks)) as executor:
                list(executor.map(lambda pair: validate_and_store(pair[0], pair[1]), enumerate(chunks)))

            # Now parse the results and update verdict_by_url
            for chunk_idx, chunk in enumerate(chunks):
                chunk_results = results_by_chunk[chunk_idx]
                if chunk_results is not None:
                    # Map results by ID
                    results_by_id = {item.id: item for item in chunk_results}
                    for idx, ann in enumerate(chunk):
                        item = results_by_id.get(idx)
                        if item is not None:
                            verdict_by_url[ann.url] = item.is_tech_job
                            print(
                                f"🤖 AI Val (Chunk {chunk_idx+1}, Job {idx+1}): {ann.organism} -> "
                                f"is_tech_job={item.is_tech_job} "
                                f"(conf: {item.confidence}, title: {item.job_title})",
                                file=sys.stderr
                            )
                        else:
                            # If Gemini response missed this ID, default to True (recall bias)
                            verdict_by_url[ann.url] = True
                            print(
                                f"⚠️ AI Val (Chunk {chunk_idx+1}, Job {idx+1}): Missing from response. Keeping by default (recall-bias).",
                                file=sys.stderr
                            )
                else:
                    # If validation of this chunk failed, default to True for all its jobs
                    for idx, ann in enumerate(chunk):
                        verdict_by_url[ann.url] = True
                        print(
                            f"⚠️ AI Val (Chunk {chunk_idx+1}, Job {idx+1}) failed. Keeping by default (recall-bias).",
                            file=sys.stderr
                        )

            # 3. Map YES verdicts back to the full list.
            kept_urls = {url for url, verdict in verdict_by_url.items() if verdict}
            final_announcements = [ann for ann in announcements if ann.url in kept_urls]
            return final_announcements

        except Exception as e:
            print(f"⚠️ AI validation failed: {e}. Gracefully keeping all announcements.", file=sys.stderr)
            return announcements

    def _validate_chunk(self, chunk: List[ParsedAnnouncement]) -> List[JobOfferValidationItem] | None:
        if not self.enabled:
            return None

        # Prepare the JSON list of jobs
        jobs_to_send = []
        for idx, ann in enumerate(chunk):
            desc = ann.description
            if len(desc) > 1500:
                desc = desc[:1500] + "..."
            jobs_to_send.append({
                "id": idx,
                "text": desc
            })
        
        jobs_json_str = json.dumps(jobs_to_send, ensure_ascii=False)
        
        # Simple and safe string replacement to avoid KeyError from curly braces in source text
        formatted_prompt = self.user_prompt_template
        if "{jobs_json}" in formatted_prompt:
            formatted_prompt = formatted_prompt.replace("{jobs_json}", jobs_json_str)
        else:
            formatted_prompt = formatted_prompt.replace("{extracted_text}", jobs_json_str)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model="gemini-3.5-flash",
                    contents=formatted_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self.system_prompt,
                        response_mime_type="application/json",
                        response_schema=JobOfferValidationBatch,
                        thinking_config=types.ThinkingConfig(thinking_level="low")
                    )
                )

                if not response.text:
                    raise ValueError("Model returned empty response text")

                batch_result = JobOfferValidationBatch.model_validate_json(response.text)
                return batch_result.results

            except Exception as e:
                # Handle 429 Too Many Requests (Rate limit) or 503 (Unavailable)
                is_429 = False
                is_503 = False
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    is_429 = True
                if "503" in err_str or "UNAVAILABLE" in err_str:
                    is_503 = True

                for attr in ("code", "status_code"):
                    if hasattr(e, attr):
                        code = getattr(e, attr)
                        if code == 429:
                            is_429 = True
                        elif code == 503:
                            is_503 = True

                if is_429:
                    print(
                        f"⏳ API rate limit (429) reached. Sleeping for 60 seconds before retrying "
                        f"(attempt {attempt + 1}/{max_retries})...",
                        file=sys.stderr
                    )
                    time.sleep(60.0)
                elif is_503:
                    print(
                        f"⏳ API service unavailable (503) reached. Sleeping for 10 seconds before retrying "
                        f"(attempt {attempt + 1}/{max_retries})...",
                        file=sys.stderr
                    )
                    time.sleep(10.0)
                else:
                    print(
                        f"⚠️ Error during Gemini validation attempt {attempt + 1}: {e}",
                        file=sys.stderr
                    )
                    if attempt < max_retries - 1:
                        time.sleep(2.0)

        return None

